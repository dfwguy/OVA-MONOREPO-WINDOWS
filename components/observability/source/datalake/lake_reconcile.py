#!/usr/bin/env python3
"""Periodically reconcile Slurm accounting and preserved results into Parquet."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("LAKE_ROOT", "/data/lake"))
STATE = ROOT / "_state" / "reconcile.json"
INTERVAL = max(60, int(os.environ.get("RECONCILE_INTERVAL_SECONDS", "300")))
SINCE = os.environ.get("RECONCILE_SINCE", "2026-08-20")
HERE = Path(__file__).resolve().parent


def write_state(payload: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(f".json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    os.replace(tmp, STATE)


def run_once() -> bool:
    started = time.time()
    commands = [
        [sys.executable, str(HERE / "lake_job_census.py"), "--since", SINCE],
        [sys.executable, str(HERE / "lake_result_map.py"), "--parse"],
    ]
    outputs = []
    ok = True
    for command in commands:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=900,
                              check=False)
        outputs.append({"argv": command[1:], "returncode": proc.returncode,
                        "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]})
        if proc.returncode:
            ok = False
            break
    previous = {}
    try:
        previous = json.loads(STATE.read_text())
    except (OSError, ValueError):
        pass
    state = {
        "ok": ok,
        "started_at": started,
        "finished_at": time.time(),
        "duration_seconds": round(time.time() - started, 3),
        "last_success_at": time.time() if ok else previous.get("last_success_at"),
        "commands": outputs,
    }
    write_state(state)
    print(json.dumps({k: state[k] for k in ("ok", "finished_at", "duration_seconds")}),
          flush=True)
    return ok


def main() -> int:
    while True:
        run_once()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
