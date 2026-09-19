#!/usr/bin/env python
"""KnowLP trajectory recording — TrajectoryNode → trajectory.jsonl (§6.5)

Strategy (two streams + join; see docs/task-state-modulation-design.md §6.5 / §6.6):
- At retrieval time one complete row (s, a, s') is written: query / task_state snapshot / gains / retrieved /
  drift_score / version — all seven fields exist at retrieval time, written in one shot.
- consumed/rejected (real T2 chosen≻rejected) arrive asynchronously via the feedback stream and are NEVER
  backfilled into this file; §6.6.3 featurization joins them by session_id + step + ts into full
- trajectory.jsonl is append-only (single write per line); session-scoped.

Storage-agnostic (§0.0): this module does not import config; the write path is injected by the caller.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict, field
from pathlib import Path


MODULATOR_VERSION = "v0"


@dataclass
class TrajectoryNode:
    step: int
    ts: float
    session_id: str
    query: str
    task_state: dict            # task-state snapshot at that step (mu/count)
    gains: dict[str, float]     # modulation gains (who got boosted/damped; subset of retrieved)
    retrieved: list[str]        # nodes returned this step (after top_k cut)
    consumed: list[str] = field(default_factory=list)  # T2 chosen — async, §6.6.3 join
    rejected: list[str] = field(default_factory=list)  # T2 rejected — same as above
    drift_score: float = 0.0    # drift score (v0 used gains attention entropy as a placeholder)
    version: str = MODULATOR_VERSION  # modulator version (auditable)

    def to_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def gains_entropy(gains: dict[str, float]) -> float:
    """Attention-entropy placeholder: normalized entropy of the gains distribution [0,1].
    High entropy = flattened weights = lost focus = potential drift (§6.5 passive signal; v0 only records)."""
    vals = [g for g in gains.values() if g > 0]
    if len(vals) < 2:
        return 0.0
    total = sum(vals)
    probs = [v / total for v in vals]
    ent = -sum(p * math.log(p) for p in probs if p > 0)
    return round(ent / math.log(len(vals)), 4)


class TrajectoryRecorder:
    """Trajectory writer: append-only, passive recording (session/step managed by the caller)."""

    def __init__(self, path):
        self.path = Path(path)
        self._steps: dict[str, int] = {}
        self._seeded: set[str] = set()

    def _count_session_rows(self, session_id: str) -> int:
        """Rows already on disk for this session."""
        seen = 0
        try:
            with open(self.path, encoding='utf-8') as f:
                for line in f:
                    if session_id not in line:  # cheap pre-filter before parsing
                        continue
                    try:
                        if json.loads(line).get('session_id') == session_id:
                            seen += 1
                    except ValueError:
                        continue
        except OSError:
            return 0
        return seen

    def next_step(self, session_id: str) -> int:
        """Monotonic per-session step index — the row handle the T2 join matches on.

        Seeded from the file on first use rather than from a bare in-memory
        counter: a per-day session id (mcp-session-<date>) outlives the server
        process, so a counter that restarts at 0 would collide with rows written
        earlier the same day. Assumes a single writer per trajectory file.
        """
        if session_id not in self._seeded:
            self._steps[session_id] = self._count_session_rows(session_id)
            self._seeded.add(session_id)
        step = self._steps.get(session_id, 0)
        self._steps[session_id] = step + 1
        return step

    def record(self, node: TrajectoryNode) -> None:
        try:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(node.to_line() + '\n')
        except OSError:
            # trajectory write failures never block the retrieval main path
            pass
