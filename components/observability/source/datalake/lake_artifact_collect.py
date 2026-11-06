#!/usr/bin/env python3
"""
lake_artifact_collect.py — push run artifacts into the lake. STDLIB ONLY.

Runs wherever the files actually are (the head node, the rack-status container,
a Slurm prolog) and POSTs them to nvis-lakewriter's /v1/artifacts endpoint. No
pyarrow, no requests, no shared filesystem with the lake — deliberately, so it
can be dropped onto a bring-up host with nothing installed.

TYPICAL USE — capture the exact inputs of a run, at submit time:

  python3 lake_artifact_collect.py \\
      --url http://127.0.0.1:9410/v1/artifacts \\
      --run-id IREN_MKZ-llmb-nccl_single-rack01-j48727 \\
      --harness llmb --job-id 48727 --rack rack01 \\
      --root /opt/llmb-bringup/IREN_MKZ8k_llmbrun \\
      --file /opt/observability/nvis-rack-status-v3/bin/scripts/nccl_allreduce.sbatch \\
      --synthesized launch_cmdline "llmb-run submit -w nccl -s ... --scale 72" \\
      --env-snapshot

  # what would be sent, without sending it:
  python3 lake_artifact_collect.py --root <dir> --run-id R --dry-run

SUITE SNAPSHOT — capture the validation suite itself, unattached to any run:

  python3 lake_artifact_collect.py --root <suite> --capture-kind suite_snapshot \\
      --run-id IREN_MKZ-suitesnap-<name>-t<epoch>

DEFAULT SELECTION under --root (override with --include/--exclude globs):
  conf/*.conf  conf/profiles/*.conf  conf/inventory/*  jobs/*.sbatch
  jobs/**/*.dat  *.yaml/*.yml  lib/*.sh  *.env
Binary or non-UTF8 files are sent base64; everything is sha256'd BEFORE the wire
so the server can prove nothing changed in flight.
"""
from __future__ import annotations

import argparse
import base64
import fnmatch
import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_INCLUDES = [
    "conf/*.conf",
    "conf/profiles/*.conf",
    "conf/inventory/*",
    "jobs/*.sbatch",
    "jobs/**/*.dat",
    "jobs/**/*.sbatch",
    "*.yaml", "*.yml",
    "conf/**/*.yaml", "conf/**/*.yml",
    "lib/*.sh",
    "*.env",
    "*.manifest.json",
]
DEFAULT_EXCLUDES = [
    "*/.git/*", "*/tests/fixtures/*", "*/node_modules/*", "*.pyc",
]
MAX_FILE_BYTES = 64 * 1024 * 1024


def sha256_file(p: Path) -> tuple[str, int, bytes]:
    data = p.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data), data


def wire_entry(path: str, data: bytes, mtime: float | None) -> dict:
    """utf8 on the wire when the bytes round-trip, else base64. Always sha256'd."""
    try:
        text = data.decode("utf-8")
        enc, content = ("utf8", text) if text.encode("utf-8") == data else \
                       ("base64", base64.b64encode(data).decode("ascii"))
    except UnicodeDecodeError:
        enc, content = "base64", base64.b64encode(data).decode("ascii")
    e = {
        "artifact_path": path,
        "encoding": enc,
        "content": content,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }
    if mtime is not None:
        e["mtime"] = mtime
    return e


def select_files(root: Path, includes, excludes):
    hits = []
    for pat in includes:
        for p in sorted(root.glob(pat)):
            if p.is_file():
                hits.append(p)
    seen, out = set(), []
    for p in hits:
        rp = str(p.resolve())
        if rp in seen:
            continue
        if any(fnmatch.fnmatch(rp, x) for x in excludes):
            continue
        seen.add(rp)
        out.append(p)
    return out


def build_payload(args) -> dict:
    arts = []
    files = []
    if args.root:
        files += select_files(Path(args.root),
                              args.include or DEFAULT_INCLUDES,
                              (args.exclude or []) + DEFAULT_EXCLUDES)
    files += [Path(f) for f in (args.file or [])]

    for p in files:
        try:
            st = p.stat()
        except OSError as e:
            print(f"WARN skip {p}: {e}", file=sys.stderr)
            continue
        if st.st_size > MAX_FILE_BYTES:
            print(f"WARN skip {p}: {st.st_size}B > MAX_FILE_BYTES", file=sys.stderr)
            continue
        _sha, _n, data = sha256_file(p)
        arts.append(wire_entry(str(p.resolve()), data, st.st_mtime))

    for name, text in (args.synthesized or []):
        arts.append(wire_entry(f"synthesized:{name}", text.encode("utf-8"), None))

    if args.env_snapshot:
        keep = {k: v for k, v in os.environ.items()
                if k.split("_")[0] in ("NCCL", "UCX", "OMPI", "NVIS", "SLURM",
                                       "LLMB", "CUDA", "MPI", "PMIX")}
        body = "\n".join(f"{k}={v}" for k, v in sorted(keep.items())) + "\n"
        arts.append(wire_entry("synthesized:env_snapshot",
                               body.encode("utf-8"), None))

    payload = {
        "run_id": args.run_id,
        "cluster": args.cluster,
        "job_id": args.job_id,
        "harness": args.harness,
        "capture_kind": args.capture_kind,
        "source_host": args.source_host or socket.gethostname(),
        "captured_by": args.captured_by or f"lake_artifact_collect/{os.getpid()}",
        "fixture": bool(args.fixture),
        "artifacts": arts,
    }
    if args.node:
        payload["node"] = args.node
    if args.rack:
        payload["rack"] = args.rack
    if args.su:
        payload["su"] = args.su
    if args.captured_at:
        payload["captured_at"] = float(args.captured_at)

    # Resolution context: ${VAR} in one conf usually resolves against another
    # (workloads.conf thresholds -> the platform profile). Build it from every
    # KEY=VALUE line we are already shipping so the server can record `resolved`.
    ctx = {}
    for a in arts:
        if a["encoding"] != "utf8":
            continue
        if not a["artifact_path"].endswith((".conf", ".env")):
            continue
        for line in a["content"].splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            k = k.replace("export ", "").strip()
            if k.replace("_", "").isalnum():
                ctx[k] = v.strip().strip("'\"")
    if ctx:
        payload["resolve_context"] = ctx
    return payload


def post(url: str, payload: dict, inline_max: int | None, timeout: float):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if inline_max is not None:
        req.add_header("X-Lake-Inline-Max", str(inline_max))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get(
        "LAKE_ARTIFACT_URL", "http://127.0.0.1:9410/v1/artifacts"))
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--cluster", default=os.environ.get("CLUSTER_NAME", "IREN_MKZ"))
    ap.add_argument("--root", help="suite root to scan with --include globs")
    ap.add_argument("--file", action="append", help="explicit file (repeatable)")
    ap.add_argument("--include", action="append", help="glob under --root (repeatable)")
    ap.add_argument("--exclude", action="append", help="glob to drop (repeatable)")
    ap.add_argument("--synthesized", nargs=2, action="append",
                    metavar=("NAME", "TEXT"),
                    help="capture text that has no file, e.g. the resolved argv")
    ap.add_argument("--env-snapshot", action="store_true",
                    help="capture NCCL_*/UCX_*/OMPI_*/NVIS_*/SLURM_* from this env")
    ap.add_argument("--job-id")
    ap.add_argument("--harness", choices=["llmb", "rackstatus", "sbatch", "manual"])
    ap.add_argument("--capture-kind", default="run",
                    choices=["run", "suite_snapshot"])
    ap.add_argument("--node")
    ap.add_argument("--rack")
    ap.add_argument("--su")
    ap.add_argument("--source-host")
    ap.add_argument("--captured-by")
    ap.add_argument("--captured-at", help="epoch seconds; default now")
    ap.add_argument("--fixture", action="store_true",
                    help="mark every row synthetic/demo (fixture=true)")
    ap.add_argument("--inline-max", type=int,
                    help="ask the server to spill blobs larger than this")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    payload = build_payload(args)
    n = len(payload["artifacts"])
    total = sum(a["size_bytes"] for a in payload["artifacts"])
    if not n:
        print("nothing selected — check --root/--include/--file", file=sys.stderr)
        return 2
    if args.dry_run:
        for a in payload["artifacts"]:
            print(f"{a['sha256'][:16]}  {a['size_bytes']:>9}  {a['artifact_path']}")
        print(f"-- {n} artifacts, {total} bytes, run_id={args.run_id} "
              f"(dry-run, nothing sent)")
        return 0

    t0 = time.time()
    code, text = post(args.url, payload, args.inline_max, args.timeout)
    dt = time.time() - t0
    print(f"POST {args.url} -> {code} in {dt:.2f}s  "
          f"({n} artifacts, {total} bytes)\n{text}")
    return 0 if 200 <= code < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
