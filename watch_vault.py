#!/usr/bin/env python
"""
KnowLP-RAG: Auto-Rebuild Watcher
Polls Obsidian vault every 5 minutes. If any .md file changed, auto-rebuilds graph.
Run as: python watch_vault.py [--daemon]
"""
import json, os, sys, time, subprocess
from pathlib import Path
from datetime import datetime

from config import VAULT, GRAPH_DIR
STATE_FILE = GRAPH_DIR / ".watch_state.json"

def get_vault_signature():
    """Get a hash of all .md file sizes and mtimes. Fast, no content hashing."""
    sig = {}
    for f in VAULT.rglob("*.md"):
        parts = f.relative_to(VAULT).parts
        if any(p.startswith('.') for p in parts):
            continue
        try:
            stat = f.stat()
            sig[str(f.relative_to(VAULT))] = (stat.st_mtime, stat.st_size)
        except:
            pass
    return sig

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}

def save_state(sig):
    STATE_FILE.write_text(json.dumps(sig, ensure_ascii=False))

def rebuild():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Rebuilding graph...", flush=True)
    result = subprocess.run(
        [sys.executable, str(GRAPH_DIR / "build_graph.py")],
        capture_output=True, text=True, timeout=120,
        cwd=str(VAULT)
    )
    if result.returncode == 0:
        # Also rebuild vector index
        subprocess.run(
            [sys.executable, str(GRAPH_DIR / "vector_index.py"), "--build"],
            capture_output=True, text=True, timeout=60,
            cwd=str(VAULT)
        )
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Rebuild complete.", flush=True)
        return True
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Rebuild FAILED: {result.stderr[:200]}", flush=True)
        return False

def watch_loop(interval=300):
    """Main watch loop. interval in seconds (default 5 min)."""
    print(f"KnowLP Watcher started. Polling every {interval}s. Ctrl+C to stop.")
    old_sig = get_vault_signature()
    save_state({k: list(v) for k, v in old_sig.items()})  # convert tuples for JSON
    
    while True:
        time.sleep(interval)
        try:
            new_sig = get_vault_signature()
            
            # Check for changes
            added = set(new_sig.keys()) - set(old_sig.keys())
            removed = set(old_sig.keys()) - set(new_sig.keys())
            changed = {k for k in new_sig if k in old_sig and new_sig[k] != old_sig[k]}
            
            total_changes = len(added) + len(removed) + len(changed)
            if total_changes > 0:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] {total_changes} file(s) changed: "
                      f"+{len(added)} -{len(removed)} ~{len(changed)}", flush=True)
                if added:
                    print(f"  Added: {list(added)[:5]}...")
                if changed:
                    print(f"  Changed: {list(changed)[:5]}...")
                
                rebuild()
                old_sig = new_sig
                save_state({k: list(v) for k, v in new_sig.items()})
        except KeyboardInterrupt:
            print("\nWatcher stopped.")
            break
        except Exception as e:
            print(f"Watch error: {e}", flush=True)

if __name__ == '__main__':
    interval = 300  # 5 minutes default
    if '--fast' in sys.argv:
        interval = 60  # 1 minute for testing
    if '--once' in sys.argv:
        rebuild()
    else:
        watch_loop(interval)
