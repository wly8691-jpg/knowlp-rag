"""Real MCP stdio integration (work order 分池检索M1-M3 §二之二-2).

Spawns knowlp_mcp.py as a real stdio server, initializes the MCP session,
lists tools, then exercises knowlp_search_pools both ways:

  - pools=None against knowlp_search on the SAME query: the two responses
    must be identical (this is the B5 consistency contract, proven through
    the real pipe, not a unit-level delegation stub);
  - pools=["image"]: the pool path must answer with mode/pool_status/hits.

The pools=None leg performs REAL searches and therefore writes real
trajectory rows (that is the point — it must be the production path). The
query carries a distinctive marker so the rows are identifiable for probe
tagging later (打标须峄授权, so they are left untagged — the receipt counts
them). Runs only where the vault is configured; skips honestly otherwise.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MARKER = "MCP池一致性校验桩20261006"


def _vault_configured() -> bool:
    try:
        sys.path.insert(0, str(REPO))
        from config import VAULT_CONFIGURED
        return bool(VAULT_CONFIGURED)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _vault_configured(),
                                reason="real vault not configured on this machine")


class McpStdio:
    """Minimal line-delimited JSON-RPC client for the FastMCP stdio server."""

    def __init__(self, init_timeout: float = 90.0):
        env = dict(os.environ)
        self.proc = subprocess.Popen(
            [sys.executable, str(REPO / "knowlp_mcp.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(REPO), env=env)
        self._lines: queue.Queue = queue.Queue()
        self._errs: list = []
        threading.Thread(target=self._pump, args=(self.proc.stdout, self._lines), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.proc.stderr, None), daemon=True).start()
        self._next_id = 0
        self.init_timeout = init_timeout
        self._initialize()

    def _pump(self, stream, sink):
        for line in iter(stream.readline, b""):
            if sink is not None:
                sink.put(line)
            else:
                self._errs.append(line)   # kept only for the hang/timeout report

    def send(self, obj: dict) -> None:
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
        self.proc.stdin.flush()

    def request(self, method: str, params: dict, timeout: float = 90.0) -> dict:
        self._next_id += 1
        want = self._next_id
        self.send({"jsonrpc": "2.0", "id": want, "method": method, "params": params})
        deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                tail = b"".join(self._errs[-8:]).decode("utf-8", "replace")
                raise AssertionError(f"no response to {method} in {timeout}s\n--- stderr tail ---\n{tail}")
            try:
                line = self._lines.get(timeout=left)
            except queue.Empty:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("id") == want:
                if "error" in msg:
                    raise AssertionError(f"{method} JSON-RPC error: {json.dumps(msg['error'], ensure_ascii=False)[:400]}")
                return msg["result"]

    def _initialize(self) -> None:
        result = self.request("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "pytest-integration", "version": "1"}},
            timeout=self.init_timeout)
        assert result["serverInfo"]["name"] == "knowlp"
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call_tool(self, name: str, arguments: dict, timeout: float = 90.0) -> dict:
        result = self.request("tools/call", {"name": name, "arguments": arguments},
                              timeout=timeout)
        assert result.get("isError") is not True, f"{name} tool error: {json.dumps(result)[:400]}"
        body = result.get("structuredContent")
        if body is None:
            body = json.loads(result["content"][0]["text"])
        return body

    def close(self) -> None:
        try:
            self.proc.kill()
        except Exception:
            pass


@pytest.fixture(scope="module")
def server():
    m = McpStdio()
    yield m
    m.close()


def test_tools_registered(server):
    result = server.request("tools/list", {})
    names = [t["name"] for t in result["tools"]]
    assert "knowlp_search" in names
    assert "knowlp_search_pools" in names        # B5: wired, not test-only
    # knowlp_search's signature is untouched by this batch (红线 1)
    schema = next(t for t in result["tools"] if t["name"] == "knowlp_search")["inputSchema"]
    assert set(schema["properties"]) == {"query", "limit", "engines"}


def test_pools_none_matches_knowlp_search_over_real_stdio(server):
    # pools=None is literally knowlp_search (same function — pinned by the
    # unit test). At the integration level the comparison must dodge engine
    # nondeterminism: ripgrep's parallel walker shuffles matches and, for a
    # broad query, the limit cutoff binds — which 100 of thousands of matches
    # survive differs call-to-call EVEN BETWEEN TWO PLAIN knowlp_search CALLS
    # (measured: jaccard 0.41 baseline vs 0.29 cross-path — statistical
    # quicksand). So: a deliberately NARROW query whose hit count stays below
    # the limit keeps the cutoff unbound; then each engine returns the same
    # result SET every call and sorted-title equality is a real assertion.
    # Two real searches → 2 trajectory rows with this distinctive query.
    narrow = "奇门遁甲-数学结构"
    r_search = server.call_tool("knowlp_search", {"query": narrow, "limit": 100})
    r_pools = server.call_tool("knowlp_search_pools", {"query": narrow, "limit": 100})
    assert sorted(r_pools) == sorted(r_search)                     # same response shape
    assert sorted(h["title"] for h in r_pools["hits"]) == \
           sorted(h["title"] for h in r_search["hits"])            # same hit set
    assert r_pools["total"] == r_search["total"]
    assert r_pools["engines_used"] == r_search["engines_used"]
    assert r_pools["session_id"] == r_search["session_id"]


def test_pool_path_over_real_stdio(server):
    body = server.call_tool("knowlp_search_pools",
                            {"query": MARKER, "pools": ["image"], "limit": 5})
    assert body["mode"] == "pools" and body["shadow_mode"] is True
    assert "image" in body["pool_status"]
    assert body["pool_status"]["image"]["status"] in ("ok", "empty")
    assert isinstance(body["hits"], list)
