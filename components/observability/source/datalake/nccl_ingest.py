#!/usr/bin/env python3
"""
nccl_ingest.py — land nccl-tests sweep output into the `nccl_results` Parquet table.

This is the FILE/ARTIFACT lane of the lake, not the metrics lane. lakewriter.py is
a push-only HTTP server (remote_write / Loki / OTLP); nothing in it can ingest an
NCCL .out file. This module closes that gap for the lake's stated PRIMARY purpose:
"ingest NCCL tests ... and the final raw results".

USAGE
-----
  # parse + write Parquet
  python nccl_ingest.py ingest <log> [<log>...] [--scope rack] [--replace] [--json]
  # parse only, no writes (works without pyarrow? no — use `nccl_parse` directly)
  python nccl_ingest.py ingest <log> --dry-run
  # read back and self-check what was written
  python nccl_ingest.py verify --run-id <RUN_ID>
  # merge landing run-dirs into the curated zone
  python nccl_ingest.py compact [--date YYYY-MM-DD]

PARTITIONING (per design; deliberately NOT schema.PARTITION_KEYS)
----------------------------------------------------------------
  landing/nccl_results/cluster=<C>/date=<D>/run_id=<R>/part-<uuid>.parquet
  curated/nccl_results/cluster=<C>/date=<D>/su=<S>/rack=<K>/part-000.parquet

Landing on run_id makes a run one atomic directory: re-ingest is `rm -rf <run dir>`,
never a read-modify-write, and no partial run is ever visible. A run is only ~20-800
rows, so leaving it that way would be the classic small-file problem — `compact`
folds it to cluster/date/su/rack, which is what an analyst actually queries ("all
AllReduce busbw for SU5 this week"), keeping run_id as a sorted column where
row-group min/max still give predicate pushdown. `hour` is deliberately absent:
runs are 30-180 min apart, so hour-dirs would fragment for zero benefit.

NOTE lake_compact.py is NOT used for this table — its hourly job hardcodes the
cluster/su/rack/date/hour path shape and its TABLES list (correctly) does not
include nccl_results. `compact` here is the per-table equivalent.

FIXTURE SAFETY (there are no real NCCL runs on IREN_MKZ yet)
------------------------------------------------------------
A row is fixture if EITHER --fixture was passed OR the source text carries the
FIXTURE_NOT_REAL_DATA banner. Detection is one-directional — --no-fixture cannot
override a banner. Fixture rows get:
    source='fixture'  (non-null column)
    fixture=true      (non-null column)
    run_id='FIXTURE-…'  -> so the partition PATH says fixture too
    part-FIXTURE-<uuid>.parquet filename
    a _FIXTURE_NOT_REAL_DATA marker file dropped in the run directory
It is not possible to write a fixture row that reads as a real cluster result.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nccl_parse as NP                                    # noqa: E402
from lake_common import CLUSTER, IDENTITY, LAKE_ROOT, LANDING, ZSTD_LEVEL  # noqa: E402
from schema import NCCL_RESULTS_SCHEMA                     # noqa: E402

TABLE = "nccl_results"
CURATED = LAKE_ROOT / "curated"
NCCL_LANDING_PARTITION = ("cluster", "date", "run_id")
NCCL_CURATED_PARTITION = ("cluster", "date", "su", "rack")
FIXTURE_PREFIX = "FIXTURE-"
FIXTURE_MARKER = "_FIXTURE_NOT_REAL_DATA"
INGEST_TOOL = "nccl_ingest.py"
INGEST_VERSION = "1.0.0"

# GB300 NVL72 geometry — conf/profiles/gb300-nvl72.conf
NODES_PER_RACK = int(os.environ.get("NODES_PER_RACK", "18"))

# --- acceptance floors -------------------------------------------------------
# The suite and the MOP DISAGREE (profile says 820 GB/s for single-rack
# all_reduce, MOP §7.3C says 855). Per the design rule we do not resolve that
# here: the applied floor goes in floor_gbps/floor_source and the OTHER one is
# preserved in kv as floor_alt_gbps/floor_alt_source.
PROFILE_FLOORS = {                       # conf/profiles/gb300-nvl72.conf:10-14
    "single": {"all_reduce": 820.0, "all_gather": 620.0, "reduce_scatter": 640.0,
               "alltoall": 620.0, "sendrecv": 625.0},
    "multi": {"all_reduce": 400.0, "all_gather": 300.0, "reduce_scatter": 300.0,
              "alltoall": 250.0, "sendrecv": 300.0},      # :16-20
}
MOP_FLOORS = {                           # GB300_B300_Validation_MOP.md §7.3 A-D
    "loopback": (95.0, "mop:7.3A"),
    "single_node": (855.0, "mop:7.3B"),
    "rack": (855.0, "mop:7.3C"),
    "group": (95.0, "mop:7.3D"),
    "multi_rack": (95.0, "mop:7.3D"),
}
_MULTI_SCOPES = ("group", "multi_rack")


def _profile_floor(scope: str, collective: str):
    tier = "multi" if scope in _MULTI_SCOPES else "single"
    v = PROFILE_FLOORS[tier].get(collective)
    if v is None:
        return None, None
    return v, f"profile:gb300-nvl72:{tier}"


def resolve_floors(scope: str, collective: str, policy: str = "profile"):
    """-> (applied_gbps, applied_source, alt_gbps, alt_source)"""
    pf, ps = _profile_floor(scope, collective)
    mf, ms = MOP_FLOORS.get(scope, (None, None))
    if collective != "all_reduce":
        mf, ms = (None, None)            # the MOP only specifies AllReduce targets
    if policy == "mop" and mf is not None:
        return mf, ms, pf, ps
    if pf is not None:
        return pf, ps, mf, ms
    return mf, ms, pf, ps


def infer_scope(nnodes, unit_kind, explicit=None):
    """-> (scope, how_it_was_decided)"""
    if explicit:
        return explicit, "explicit"
    if unit_kind == "group":
        return "group", "unit_kind"
    if not nnodes:
        return "rack", "default"
    if nnodes == 1:
        # loopback vs NVLink-only is a topology-env distinction the sweep table
        # cannot show; caller must pass --scope loopback. Default to the MOP B case.
        return "single_node", "nnodes"
    if nnodes <= NODES_PER_RACK:
        return "rack", "nnodes"
    return "multi_rack", "nnodes"


def fold_hostlist(hosts) -> str:
    """Slurm-style folded hostlist: example50-dh01-h01-[01-18]."""
    groups: dict = {}
    for h in hosts:
        m = re.match(r"^(.*?)(\d+)$", h)
        if m:
            groups.setdefault((m.group(1), len(m.group(2))), []).append(int(m.group(2)))
        else:
            groups.setdefault((h, 0), []).append(None)
    out = []
    for (pfx, width), nums in groups.items():
        if width == 0:
            out.append(pfx)
            continue
        nums = sorted(set(nums))
        ranges, start, prev = [], nums[0], nums[0]
        for n in nums[1:]:
            if n == prev + 1:
                prev = n
                continue
            ranges.append((start, prev))
            start = prev = n
        ranges.append((start, prev))
        body = ",".join(f"{a:0{width}d}" if a == b else f"{a:0{width}d}-{b:0{width}d}"
                        for a, b in ranges)
        single = len(ranges) == 1 and ranges[0][0] == ranges[0][1]
        out.append(f"{pfx}{body}" if single else f"{pfx}[{body}]")
    return ",".join(sorted(out))


def _ts_for(path: str, override: str | None):
    if override:
        # suite stamps are '%Y-%m-%dT%H:%M:%S%z' with NO colon in the offset —
        # datetime.fromisoformat rejects that before 3.11, so parse explicitly.
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(override, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp() * 1_000_000), "explicit"
            except ValueError:
                continue
        raise SystemExit(f"--run-ts not parseable: {override!r}")
    try:
        return int(os.path.getmtime(path) * 1_000_000), "file_mtime"
    except OSError:
        return int(datetime.now(tz=timezone.utc).timestamp() * 1_000_000), "now"


# --- build rows --------------------------------------------------------------
def build_rows(path: str, args) -> tuple[list, dict]:
    pr = NP.parse_nccl_log(path)
    ident = NP.derive_run_identity(path, cluster=CLUSTER, overrides=_ident_overrides(args))

    is_fixture = bool(pr.fixture or args.fixture)      # banner can only turn it ON
    run_id = ident["run_id"]
    if is_fixture and not run_id.startswith(FIXTURE_PREFIX):
        run_id = FIXTURE_PREFIX + run_id
    if (not is_fixture) and run_id.startswith(FIXTURE_PREFIX):
        raise SystemExit(f"refusing to write non-fixture rows under {run_id!r}")

    nnodes = pr.nnodes or ident.get("nnodes_hint")
    scope, scope_src = infer_scope(nnodes, ident.get("unit_kind"), args.scope)

    # identity: host -> (su, rack); fall back to the unit_id from the log name
    su, rack = ("UNKNOWN", "UNKNOWN")
    if pr.hosts:
        su, rack = IDENTITY.lookup(pr.hosts[0])
    if rack == "UNKNOWN" and ident.get("unit_kind") == "rack":
        rack = ident.get("unit_id") or "UNKNOWN"
    su = args.su or su
    rack = args.rack or rack

    ts_us, ts_src = _ts_for(path, args.run_ts)
    nodelist = fold_hostlist(pr.hosts) if pr.hosts else (args.nodelist or "")

    base_kv = dict(pr.kv)
    base_kv.update({
        "scope_source": scope_src, "ts_source": ts_src,
        "ingest_tool": INGEST_TOOL, "ingest_version": INGEST_VERSION,
        "dialects": ",".join(sorted(pr.dialects)) or "none",
        "unit_kind": str(ident.get("unit_kind", "")),
        "run_seq": str(ident.get("run_seq", 1)),
        "floor_policy": args.floor_policy,
    })
    if pr.exit_rc is not None:
        base_kv["harness_exit_rc"] = str(pr.exit_rc)
    if pr.oob_count is not None:
        base_kv["oob_count"] = str(pr.oob_count)
    if pr.validation_enabled is not None:
        base_kv["validation"] = "1" if pr.validation_enabled else "0"
    if pr.warnings:
        base_kv["parse_warnings"] = str(len(pr.warnings))

    rows = []
    for r in pr.rows:
        coll = r["collective"]
        floor, floor_src, alt, alt_src = resolve_floors(scope, coll, args.floor_policy)
        kv = dict(base_kv)
        kv["dialect"] = r["dialect"]
        if alt is not None:
            kv["floor_alt_gbps"] = f"{alt:g}"
            kv["floor_alt_source"] = alt_src or ""
        rows.append({
            "ts": ts_us,
            "cluster": CLUSTER, "su": su, "rack": rack,
            "run_id": run_id, "unit_key": ident["unit_key"],
            "job_id": ident.get("job_id"),
            "harness": ident.get("harness"), "workload": ident.get("workload"),
            "scope": scope, "collective": coll, "round": r["round"],
            "iter_label": ident.get("iter_label"),
            "placement": r["placement"],
            "size_bytes": r["size_bytes"], "count_elems": r["count_elems"],
            "dtype": r["dtype"], "redop": r["redop"], "root": r["root"],
            "time_us": r["time_us"], "algbw_gbps": r["algbw_gbps"],
            "busbw_gbps": r["busbw_gbps"], "wrong": r["wrong"],
            "nranks": pr.nranks, "nnodes": nnodes,
            "gpus_per_node": pr.gpus_per_node,
            "nodelist": nodelist,
            "nccl_version": pr.nccl_version, "nccl_lib_path": pr.nccl_lib_path,
            "nccl_tests_bin": pr.nccl_tests_bin, "transport": pr.transport,
            "floor_gbps": floor, "floor_source": floor_src,
            "verdict": None, "is_peak": False,
            "avg_busbw_gbps": pr.avg_busbw_gbps, "oob_ok": pr.oob_ok,
            "src_file": pr.src_file, "src_lineno": r["src_lineno"],
            "kv": kv,
            "source": "fixture" if is_fixture else "live",
            "fixture": is_fixture,
        })

    _mark_peaks(rows)
    meta = {
        "src_file": pr.src_file, "run_id": run_id, "rows": len(rows),
        "fixture": is_fixture, "scope": scope, "su": su, "rack": rack,
        "nnodes": nnodes, "nranks": pr.nranks, "nodelist": nodelist,
        "dialects": sorted(pr.dialects), "collectives": sorted({r["collective"] for r in rows}),
        "parse_warnings": pr.warnings,
    }
    return rows, meta


def _mark_peaks(rows):
    """
    is_peak marks the row a scorer would use: out-of-place, largest message size,
    per (run_id, collective, round). verdict is set ONLY on those rows — every
    other row is a sweep point, not a pass/fail decision.
    """
    best: dict = {}
    for r in rows:
        if r["placement"] != "out_of_place" or r["busbw_gbps"] is None:
            continue
        k = (r["run_id"], r["collective"], r["round"])
        cur = best.get(k)
        cand = (r["size_bytes"] or 0, r["busbw_gbps"] or 0.0)
        if cur is None or cand > (cur["size_bytes"] or 0, cur["busbw_gbps"] or 0.0):
            best[k] = r
    for r in best.values():
        r["is_peak"] = True
        f = r["floor_gbps"]
        if f is not None and r["busbw_gbps"] is not None:
            ok = r["busbw_gbps"] >= f
            if r["oob_ok"] is False or (r["wrong"] or 0) > 0:
                ok = False
            r["verdict"] = "pass" if ok else "fail"


def _ident_overrides(args) -> dict:
    o = {}
    for k in ("run_id", "unit_key", "job_id", "harness", "workload", "unit_id",
              "unit_kind", "iter_label"):
        v = getattr(args, k, None)
        if v:
            o[k] = v
    if getattr(args, "run_seq", None):
        o["run_seq"] = args.run_seq
    return o


# --- arrow / parquet ---------------------------------------------------------
def to_table(rows) -> pa.Table:
    cols = {}
    for f in NCCL_RESULTS_SCHEMA:
        if f.name == "kv":
            cols["kv"] = pa.array([list((r.get("kv") or {}).items()) for r in rows],
                                  type=f.type)
        elif f.name == "ts":
            cols["ts"] = pa.array([r.get("ts") for r in rows], type=f.type)
        else:
            cols[f.name] = pa.array([r.get(f.name) for r in rows], type=f.type)
    return pa.Table.from_pydict(cols, schema=NCCL_RESULTS_SCHEMA)


def landing_dir(cluster: str, date: str, run_id: str) -> Path:
    return LANDING / TABLE / f"cluster={cluster}" / f"date={date}" / f"run_id={run_id}"


def write_landing(rows, replace=False) -> list:
    """Group rows by (cluster, date, run_id) and write one atomic Parquet each."""
    groups: dict = {}
    for r in rows:
        d = datetime.fromtimestamp(r["ts"] / 1e6, tz=timezone.utc).strftime("%Y-%m-%d")
        groups.setdefault((r["cluster"], d, r["run_id"]), []).append(r)

    written = []
    for (cluster, date, run_id), grp in groups.items():
        d = landing_dir(cluster, date, run_id)
        d.mkdir(parents=True, exist_ok=True)
        if replace:
            for old in d.glob("part-*.parquet"):
                old.unlink()
        is_fx = bool(grp[0]["fixture"])
        if is_fx:
            (d / FIXTURE_MARKER).write_text(
                "Synthetic NCCL fixture data. NOT a real IREN_MKZ run.\n"
                f"run_id={run_id}\nwritten_by={INGEST_TOOL} {INGEST_VERSION}\n"
                f"written_at={datetime.now(tz=timezone.utc).isoformat()}\n")
        tbl = to_table(grp).sort_by([("collective", "ascending"), ("round", "ascending"),
                                     ("size_bytes", "ascending"),
                                     ("placement", "ascending")])
        name = f"part-{FIXTURE_PREFIX if is_fx else ''}{uuid.uuid4().hex}.parquet"
        tmp = d / (name + ".tmp")
        pq.write_table(tbl, tmp, compression="zstd", compression_level=ZSTD_LEVEL,
                       use_dictionary=True, write_statistics=True)
        os.replace(tmp, d / name)                       # atomic
        written.append({"path": str(d / name), "rows": tbl.num_rows,
                        "run_id": run_id, "date": date, "fixture": is_fx,
                        "bytes": (d / name).stat().st_size})
    return written


# --- subcommands -------------------------------------------------------------
def cmd_ingest(args) -> int:
    all_rows, metas = [], []
    for p in args.logs:
        rows, meta = build_rows(p, args)
        if not rows:
            meta["error"] = "no data rows parsed"
        all_rows.extend(rows)
        metas.append(meta)

    out = {"tool": INGEST_TOOL, "version": INGEST_VERSION, "table": TABLE,
           "lake_root": str(LAKE_ROOT), "sources": metas,
           "total_rows": len(all_rows), "written": []}

    if args.dry_run:
        out["dry_run"] = True
        if args.sample:
            out["sample"] = [{k: v for k, v in r.items() if k != "kv"}
                             for r in all_rows[:args.sample]]
    elif all_rows:
        out["written"] = write_landing(all_rows, replace=args.replace)

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        for m in metas:
            print(f"parsed {m['rows']:4d} rows  fixture={m['fixture']}  "
                  f"scope={m['scope']}  su={m['su']} rack={m['rack']}  "
                  f"dialects={','.join(m['dialects'])}  <- {m['src_file']}")
            for w in m.get("parse_warnings", []):
                print(f"  WARN {w}")
        for w in out["written"]:
            print(f"wrote {w['rows']:4d} rows  {w['bytes']:7d} B  {w['path']}")
    return 0 if all_rows else 1


def _scan_landing(run_id=None, date=None):
    root = LANDING / TABLE
    if not root.exists():
        return []
    pat = f"cluster=*/date={date or '*'}/run_id={run_id or '*'}/part-*.parquet"
    return sorted(root.glob(pat))


def cmd_verify(args) -> int:
    files = _scan_landing(args.run_id, args.date)
    if not files:
        print(f"no landing files under {LANDING / TABLE} "
              f"(run_id={args.run_id}, date={args.date})", file=sys.stderr)
        return 1
    tbl = ds.dataset([str(f) for f in files], format="parquet").to_table()
    checks, ok = [], True

    def chk(name, cond, detail=""):
        nonlocal ok
        checks.append({"check": name, "pass": bool(cond), "detail": detail})
        ok = ok and bool(cond)

    chk("schema_matches_NCCL_RESULTS_SCHEMA",
        tbl.schema.equals(NCCL_RESULTS_SCHEMA, check_metadata=False),
        f"{tbl.num_columns} cols")
    src = set(tbl.column("source").to_pylist())
    fx = set(tbl.column("fixture").to_pylist())
    chk("source_non_null", None not in src, str(sorted(src)))
    chk("fixture_non_null", None not in fx, str(sorted(fx)))
    # every fixture row must live under a FIXTURE- run_id, and vice versa
    bad = [i for i, (s, f, r) in enumerate(zip(tbl.column("source").to_pylist(),
                                               tbl.column("fixture").to_pylist(),
                                               tbl.column("run_id").to_pylist()))
           if (s == "fixture") != bool(f) or bool(f) != r.startswith(FIXTURE_PREFIX)]
    chk("fixture_labelling_consistent", not bad, f"{len(bad)} mismatched rows")
    chk("busbw_present", tbl.column("busbw_gbps").null_count == 0,
        f"{tbl.column('busbw_gbps').null_count} nulls")
    chk("placement_domain",
        set(tbl.column("placement").to_pylist()) <= set(NP.PLACEMENTS),
        str(sorted(set(tbl.column("placement").to_pylist()))))
    npeak = sum(1 for v in tbl.column("is_peak").to_pylist() if v)
    ncr = len({(a, b, c) for a, b, c in zip(tbl.column("run_id").to_pylist(),
                                            tbl.column("collective").to_pylist(),
                                            tbl.column("round").to_pylist())})
    chk("one_peak_per_run_collective_round", npeak == ncr, f"{npeak} peaks / {ncr} groups")
    verdicts = [v for v in tbl.column("verdict").to_pylist() if v is not None]
    chk("verdict_only_on_peaks", len(verdicts) == npeak,
        f"{len(verdicts)} verdicts / {npeak} peaks")

    out = {"files": [str(f) for f in files], "rows": tbl.num_rows,
           "checks": checks, "all_pass": ok}
    print(json.dumps(out, indent=2))
    return 0 if ok else 2


def cmd_compact(args) -> int:
    """Merge landing run-dirs -> curated/cluster=/date=/su=/rack=/part-000.parquet."""
    files = _scan_landing(None, args.date)
    if not files:
        print("nothing to compact", file=sys.stderr)
        return 1
    tbl = ds.dataset([str(f) for f in files], format="parquet").to_table()
    groups: dict = {}
    keys = list(zip(tbl.column("cluster").to_pylist(),
                    [datetime.fromtimestamp(t.value / 1e6, tz=timezone.utc).strftime("%Y-%m-%d")
                     for t in tbl.column("ts")],
                    tbl.column("su").to_pylist(), tbl.column("rack").to_pylist()))
    for i, k in enumerate(keys):
        groups.setdefault(k, []).append(i)

    written = []
    for (cluster, date, su, rack), idx in groups.items():
        sub = tbl.take(pa.array(idx)).sort_by(
            [("run_id", "ascending"), ("collective", "ascending"),
             ("round", "ascending"), ("size_bytes", "ascending")])
        d = (CURATED / TABLE / f"cluster={cluster}" / f"date={date}" /
             f"su={su}" / f"rack={rack}")
        d.mkdir(parents=True, exist_ok=True)
        name = "part-000.parquet"
        tmp = d / (name + ".tmp")
        pq.write_table(sub, tmp, compression="zstd", compression_level=9,
                       use_dictionary=True, write_statistics=True,
                       row_group_size=1_000_000)
        # round-trip the row count before anything is deleted (lake_compact.py's rule)
        if pq.ParquetFile(tmp).metadata.num_rows != sub.num_rows:
            tmp.unlink()
            raise SystemExit(f"row count did not round-trip for {d}")
        os.replace(tmp, d / name)
        written.append({"path": str(d / name), "rows": sub.num_rows})
    print(json.dumps({"compacted": written, "landing_files": len(files)}, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nccl_ingest.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("ingest", help="parse nccl-tests logs -> nccl_results Parquet")
    i.add_argument("logs", nargs="+")
    i.add_argument("--scope", choices=["loopback", "single_node", "rack", "group",
                                       "multi_rack"])
    i.add_argument("--floor-policy", choices=["profile", "mop"], default="profile",
                   help="which acceptance floor to APPLY; the other is kept in kv")
    i.add_argument("--fixture", action="store_true",
                   help="force fixture labelling (the in-file banner also forces it)")
    i.add_argument("--run-ts", help="run completion time; default = source file mtime")
    i.add_argument("--rack"), i.add_argument("--su"), i.add_argument("--nodelist")
    i.add_argument("--run-id"), i.add_argument("--unit-key"), i.add_argument("--job-id")
    i.add_argument("--harness"), i.add_argument("--workload"), i.add_argument("--unit-id")
    i.add_argument("--unit-kind"), i.add_argument("--iter-label")
    i.add_argument("--run-seq", type=int)
    i.add_argument("--replace", action="store_true",
                   help="drop existing part-*.parquet in the run dir first (idempotent re-ingest)")
    i.add_argument("--dry-run", action="store_true")
    i.add_argument("--sample", type=int, default=0, help="with --dry-run: dump N rows")
    i.add_argument("--json", action="store_true")
    i.set_defaults(func=cmd_ingest)

    v = sub.add_parser("verify", help="read landing Parquet back and self-check")
    v.add_argument("--run-id"), v.add_argument("--date")
    v.set_defaults(func=cmd_verify)

    c = sub.add_parser("compact", help="landing run-dirs -> curated cluster/date/su/rack")
    c.add_argument("--date")
    c.set_defaults(func=cmd_compact)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
