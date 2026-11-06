#!/usr/bin/env python3
"""
nvis-lake-compact — hourly/daily compaction + retention for the IREN_MKZ lake.

Reads many small landing files for a closed partition, rewrites them as few
large, node/switch+ts-sorted, ZSTD-9 curated files, verifies the row count, then
deletes the landing inputs. Idempotent + resumable (bookmark = _SUCCESS marker).
Also enforces retention/rollup by cheap directory delete.

Runs from a systemd timer (not a daemon) so a crash never corrupts in-flight
parquet. Uses DuckDB when available (fast, SQL rewrite) else pyarrow.dataset.

Usage:
  lake_compact.py hourly    # compact previous closed hour across all tables
  lake_compact.py daily     # roll hour files -> day file + apply retention

Env: LAKE_ROOT, LATE_GRACE_HOURS(2), RAW_RETENTION_DAYS(90), LOG_RETENTION_DAYS(180)
"""
from __future__ import annotations
import json
import tempfile
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pyarrow as pa

from schema import SORT_KEY

LAKE_ROOT = Path(os.environ.get("LAKE_ROOT", "/data/lake"))
LANDING = LAKE_ROOT / "landing"
CURATED = LAKE_ROOT / "curated"
LATE_GRACE_H = int(os.environ.get("LATE_GRACE_HOURS", "2"))

# ---- RETENTION POLICY ------------------------------------------------------
# The shipped defaults (90d raw / 180d logs) DO NOT FIT this NVMe. /data is a
# single 7.0T /dev/nvme2n1 shared by VictoriaMetrics (/data/vm, 12-month
# retention, ~1.5T), Loki (/data/loki, ~0.3-0.8T) and this lake, leaving a
# realistic lake budget near 4.1T. At the projected full-fleet rate of
# ~40,000 samples/s -> ~3.46e9 rows/day -> ~17 GB/day curated, 90 days of raw
# metrics alone is ~1.6-3.1T and 180 days of logs would blow the budget.
#
# POLICY (all overridable by env, set in systemd/nvis-lake-compact@.service):
#   metrics/fabric_phy/switch_events  raw  30 days
#   logs                              raw  45 days
#   metrics 1-minute rollup                365 days   (4x reduction vs 15s)
#   validation_runs                        forever    (handover provenance)
# Age-based retention alone does NOT bound bytes if the ingest rate grows, so
# LAKE_MAX_BYTES is enforced on top as a hard byte ceiling (see enforce_budget).
RAW_RET_D = int(os.environ.get("RAW_RETENTION_DAYS", "30"))
LOG_RET_D = int(os.environ.get("LOG_RETENTION_DAYS", "45"))
ROLLUP_RET_D = int(os.environ.get("ROLLUP_RETENTION_DAYS", "365"))
# Hard ceiling on total lake bytes. 4 TiB of the 7.0T device, leaving room for
# VM (12mo) + Loki (31d) + the writer's own 200 GiB MIN_FREE_BYTES reserve.
LAKE_MAX_BYTES = int(os.environ.get("LAKE_MAX_BYTES", str(4 * 1024 ** 4)))
# Independent floor: never let the device itself run out from under VM/Loki.
MIN_FREE_BYTES = int(os.environ.get("COMPACT_MIN_FREE_BYTES", str(300 * 1024 ** 3)))

# validation_runs kept forever (handover provenance) — see run_daily().
TABLES = ["metrics", "logs", "fabric_phy", "switch_events", "validation_runs"]
# Tables exempt from BOTH age retention and the byte-budget trim.
KEEP_FOREVER = ("validation_runs",)
# Long-term downsampled tier: raw table -> rollup table.
ROLLUP_OF = {"metrics": "metrics_1m"}

try:
    import duckdb
except Exception:
    duckdb = None


def _closed_hour_dirs(table: str, cutoff: datetime):
    """Yield landing hour-dirs older than cutoff (past the late-data grace)."""
    base = LANDING / table
    if not base.exists():
        return
    for hourdir in base.glob("cluster=*/su=*/rack=*/date=*/hour=*"):
        parts = {kv.split("=")[0]: kv.split("=")[1]
                 for kv in hourdir.parts if "=" in kv}
        try:
            dt = datetime.strptime(f"{parts['date']} {parts['hour']}",
                                   "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if dt <= cutoff and any(hourdir.glob("**/*.parquet")):
            yield hourdir, parts, dt


def sweep_scratch():
    """Delete spill left by a previous crash. DuckDB cannot clean up after SIGKILL.

    After the 2026-08-13 OOM loop, 12,671 orphaned duckdb_temp_block-*.block
    files held 1.2 TB — enough to fill the device that also hosts VictoriaMetrics
    and Loki. Only our own scratch pattern is removed, never lake data.
    """
    spill = Path(os.environ.get("LAKE_COMPACT_TEMP", str(LAKE_ROOT / "tmp")))
    n = freed = 0
    for f in spill.glob("duckdb_temp_block-*.block"):
        try:
            freed += f.stat().st_size
            f.unlink()
            n += 1
        except OSError:
            pass
    if n:
        print(f"swept {n} orphaned spill blocks ({freed/1024**3:.1f} GiB) from {spill}",
              flush=True)


def compact_hour(table: str, hourdir: Path, parts: dict):
    """Merge -> sorted, ZSTD-9 curated file; verify; delete landing inputs."""
    src_files = [str(p) for p in hourdir.glob("**/*.parquet")]
    if not src_files:
        return
    # GUARD: refuse a partition that is pathologically large for ONE hour. The
    # 2026-08-06T08 partition reached 133,009 files / 89 GB because an upstream
    # replay loop rewrote the same 15 minutes 589 times; compacting it OOM-killed
    # this process every 96 s for two weeks. A single hour of one rack is ~0.5 GB.
    # Refusing loudly beats crash-looping silently.
    max_files = int(os.environ.get("LAKE_COMPACT_MAX_FILES", "20000"))
    max_bytes = int(os.environ.get("LAKE_COMPACT_MAX_BYTES", str(20 * 1024 ** 3)))
    nbytes = sum(Path(f).stat().st_size for f in src_files)
    if len(src_files) > max_files or nbytes > max_bytes:
        print(f"REFUSING {table} {parts}: {len(src_files)} files / "
              f"{nbytes/1024**3:.1f} GiB exceeds guard "
              f"({max_files} files / {max_bytes/1024**3:.0f} GiB). "
              f"An upstream producer is almost certainly looping. NOT compacting, "
              f"NOT deleting — investigate the writer.", flush=True)
        return
    dst_dir = (CURATED / table /
               f"cluster={parts['cluster']}" / f"su={parts['su']}" /
               f"rack={parts['rack']}" / f"date={parts['date']}" /
               f"hour={parts['hour']}")
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "part-000.parquet"
    sort_col = SORT_KEY.get(table)

    tmp = dst.with_suffix(".parquet.tmp")
    src_bytes = sum(Path(f).stat().st_size for f in src_files)

    # MEMORY BOUND. The original path was:
    #     tbl = ds.dataset(src_files).to_table()   # whole hour resident
    #     tbl = tbl.sort_by(...)                   # a second full copy
    # which is unbounded in the size of the hour. On 2026-08-13 that reached
    # anon-rss 104,576,456 kB -- the container's 100 GB cgroup ceiling -- and the
    # kernel OOM-killed python every ~96 s (18:57:58, 18:59:34, 19:01:10), giving
    # 2,762 restarts and 100+ oom-kills in one dmesg buffer. Raising the limit
    # only moves the ceiling: the process grows to whatever it is given.
    #
    # DuckDB streams the same sorted write and SPILLS TO DISK past memory_limit,
    # so peak RSS is bounded by config instead of by the largest hour we happen
    # to compact. The arrow path is kept for small hours, where materialising is
    # both safe and faster.
    mem_limit = os.environ.get("LAKE_COMPACT_MEM_LIMIT", "8GB")
    small = src_bytes < int(os.environ.get("LAKE_COMPACT_ARROW_MAX_BYTES",
                                           str(2 * 1024 ** 3)))
    n_in = None
    if duckdb is not None and not small:
        con = duckdb.connect()
        con.execute(f"SET memory_limit='{mem_limit}'")
        # Spill onto /data (7.0T device, 5.2T free), NOT /tmp on the 1T root.
        # A sort of an 87 GB partition can spill tens of GB; putting that on /
        # would threaten the root filesystem rather than the lake's own device.
        spill = Path(os.environ.get("LAKE_COMPACT_TEMP", str(LAKE_ROOT / "tmp")))
        spill.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{spill}'")
        con.execute("SET preserve_insertion_order=false")
        cols = pq.ParquetFile(src_files[0]).schema_arrow.names
        order = [c for c in (sort_col, "ts") if c and c in cols]
        order_sql = (" ORDER BY " + ", ".join(f'"{c}"' for c in order)) if order else ""
        n_in = con.execute("SELECT count(*) FROM read_parquet($1)",
                           [src_files]).fetchone()[0]
        con.execute(
            f"COPY (SELECT * FROM read_parquet($1){order_sql}) TO '{tmp}' "
            f"(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 9, "
            f"ROW_GROUP_SIZE 1000000)", [src_files])
        con.close()
    else:
        dataset = ds.dataset(src_files, format="parquet")
        tbl = dataset.to_table()
        n_in = tbl.num_rows
        sort_cols = [c for c in (sort_col, "ts") if c and c in tbl.column_names]
        if sort_cols:
            tbl = tbl.sort_by([(c, "ascending") for c in sort_cols])
        pq.write_table(tbl, tmp, compression="zstd", compression_level=9,
                       use_dictionary=True, write_statistics=True,
                       row_group_size=1_000_000)
        del tbl
    # verify row count round-trips before destroying landing
    n_out = pq.ParquetFile(tmp).metadata.num_rows
    if n_out != n_in:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{table} {parts}: rowcount {n_out}!={n_in}, abort")
    os.replace(tmp, dst)
    (dst_dir / "_SUCCESS").write_text(str(int(time.time())))
    for f in src_files:
        Path(f).unlink(missing_ok=True)
    # prune now-empty landing node dirs
    for d in sorted(hourdir.glob("node=*"), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    print(f"compacted {table} {parts['su']}/{parts['rack']} "
          f"{parts['date']}T{parts['hour']} rows={n_in} -> {dst}", flush=True)


def run_hourly():
    cutoff = datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0) - timedelta(hours=LATE_GRACE_H)
    for table in TABLES:
        for hourdir, parts, _ in _closed_hour_dirs(table, cutoff):
            try:
                compact_hour(table, hourdir, parts)
            except Exception as e:
                print(f"WARN compact {table} {parts}: {e}", flush=True)


def _dir_bytes(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _date_of(datedir: Path):
    try:
        return datetime.strptime(datedir.name.split("=")[-1],
                                 "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def rollup_1m(table: str, datedir: Path, parts: dict) -> bool:
    """Emit the 1-minute downsample of one curated date-dir before it is deleted.

    This is the long-term tier that turns retention from a CLIFF into a taper:
    without it, day RAW_RET_D+1 simply vanishes and a bring-up regression can no
    longer be compared against its own baseline. 15s -> 60s is a 4x row
    reduction, and min/max/avg/last per (series, minute) preserves both the
    trend and the excursions that a bare average would hide.

    Grouping must include the `labels` map or distinct series would be merged.
    pyarrow cannot group by a map column, so the map is stringified for the
    GROUP BY key only and the original map is carried through with any_value().
    Returns True when the rollup is durable (or already present).
    """
    dst_table = ROLLUP_OF.get(table)
    if not dst_table:
        return True                       # no rollup defined -> nothing to keep
    src_files = [str(p) for p in datedir.rglob("*.parquet")]
    if not src_files:
        return True
    dst_dir = (CURATED / dst_table /
               f"cluster={parts['cluster']}" / f"su={parts['su']}" /
               f"rack={parts['rack']}" / f"date={parts['date']}")
    dst = dst_dir / "part-000.parquet"
    if (dst_dir / "_SUCCESS").exists() and dst.exists():
        return True                       # idempotent: already rolled up
    if duckdb is None:
        print(f"WARN rollup {table} {parts}: duckdb unavailable, REFUSING to "
              f"delete raw without a long-term tier", flush=True)
        return False
    dst_dir.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".parquet.tmp")
    con = duckdb.connect()
    try:
        tbl = con.execute("""
            SELECT
              make_timestamp(CAST(floor(epoch_us(ts) / 60000000) * 60000000
                                  AS BIGINT))          AS ts,
              metric, cluster, su, rack, node, gpu, job, instance,
              any_value(labels)                        AS labels,
              avg(value)                               AS value_avg,
              min(value)                               AS value_min,
              max(value)                               AS value_max,
              arg_max(value, ts)                       AS value_last,
              count(*)                                 AS samples
            FROM read_parquet($1)
            GROUP BY 1, metric, cluster, su, rack, node, gpu, job, instance,
                     CAST(labels AS VARCHAR)
        """, [src_files]).fetch_arrow_table()
        n = tbl.num_rows
        tbl = tbl.sort_by([("node", "ascending"), ("metric", "ascending"),
                           ("ts", "ascending")])
        pq.write_table(tbl, tmp, compression="zstd", compression_level=9,
                       use_dictionary=True, write_statistics=True,
                       row_group_size=1_000_000)
        if pq.ParquetFile(tmp).metadata.num_rows != n:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("rollup rowcount did not round-trip")
        os.replace(tmp, dst)
        (dst_dir / "_SUCCESS").write_text(str(int(time.time())))
        print(f"rollup_1m {table} {parts['date']} {parts['su']}/{parts['rack']}: "
              f"{n} rows -> {dst}", flush=True)
        return True
    except Exception as e:
        tmp.unlink(missing_ok=True)
        print(f"WARN rollup {table} {parts}: {e}", flush=True)
        return False
    finally:
        con.close()


def _expire(datedir: Path, table: str, reason: str) -> bool:
    """Roll up (if a long-term tier is defined) then delete one curated date-dir.

    Deletion is refused when the rollup failed — losing the raw AND having no
    downsample would be silent, unrecoverable data loss.
    """
    parts = {kv.split("=")[0]: kv.split("=")[1]
             for kv in datedir.parts if "=" in kv}
    if not rollup_1m(table, datedir, parts):
        print(f"retention: KEEPING {datedir} (rollup failed)", flush=True)
        return False
    freed = _dir_bytes(datedir)
    shutil.rmtree(datedir, ignore_errors=True)
    print(f"retention[{reason}]: dropped {datedir} ({freed} bytes)", flush=True)
    return True


def _curated_datedirs(tables):
    """(date, table, dir) for every curated date-dir of the given tables."""
    for table in tables:
        base = CURATED / table
        if not base.exists():
            continue
        for datedir in base.glob("cluster=*/su=*/rack=*/date=*"):
            d = _date_of(datedir)
            if d:
                yield d, table, datedir


def enforce_budget():
    """HARD byte ceiling — the guarantee that the lake cannot fill the NVMe.

    Age-based retention bounds TIME, not BYTES: if ingest grows (the shard tier
    is dark today and will add ~30k samples/s once the compute plane is
    routable), 30 days of data silently becomes 10x larger. This trims the
    OLDEST curated raw date-dirs, rolling each into the 1-minute tier first,
    until the lake is under LAKE_MAX_BYTES and the device is above
    MIN_FREE_BYTES. Rollups and validation_runs are never trimmed here.
    """
    trim_tables = [t for t in TABLES if t not in KEEP_FOREVER]
    for _ in range(10000):
        used = _dir_bytes(LAKE_ROOT)
        free = shutil.disk_usage(LAKE_ROOT).free
        if used <= LAKE_MAX_BYTES and free >= MIN_FREE_BYTES:
            print(f"budget ok: lake={used} <= {LAKE_MAX_BYTES}, "
                  f"free={free} >= {MIN_FREE_BYTES}", flush=True)
            return
        cands = sorted(_curated_datedirs(trim_tables), key=lambda x: x[0])
        if not cands:
            print(f"WARN budget: lake={used} free={free} over budget but no "
                  f"trimmable curated data left", flush=True)
            return
        d, table, datedir = cands[0]
        print(f"budget: lake={used} free={free} -> trimming oldest "
              f"{table} {datedir.name}", flush=True)
        if not _expire(datedir, table, "budget"):
            return                        # rollup broken; stop rather than churn


def run_daily():
    """Retention: roll up + drop curated raw past policy, then enforce bytes."""
    now = datetime.now(timezone.utc)
    for table in TABLES:
        if table in KEEP_FOREVER:
            continue                      # keep forever (handover provenance)
        ret = LOG_RET_D if table == "logs" else RAW_RET_D
        for d, _t, datedir in _curated_datedirs([table]):
            if (now - d).days > ret:
                _expire(datedir, table, f"age>{ret}d")

    # Age out the long-term rollup tier itself.
    for dst in set(ROLLUP_OF.values()):
        base = CURATED / dst
        if not base.exists():
            continue
        for datedir in base.glob("cluster=*/su=*/rack=*/date=*"):
            d = _date_of(datedir)
            if d and (now - d).days > ROLLUP_RET_D:
                shutil.rmtree(datedir, ignore_errors=True)
                print(f"retention[rollup>{ROLLUP_RET_D}d]: dropped {datedir}",
                      flush=True)

    enforce_budget()


def run_scheduler():
    """In-container scheduler: hourly at :15, daily at 02:00.

    The systemd timers in datalake/systemd/ are the preferred deployment, but
    installing them needs root. This mode keeps compaction + retention ACTUALLY
    RUNNING (compose `restart: always` gives reboot survival) rather than
    leaving them as uninstalled templates — which is how the lake ended up with
    a 90d/180d policy that nothing enforced. Markers in _state/compact.json make
    a run at-most-once per hour/day even across restarts.
    """
    state_p = LAKE_ROOT / "_state" / "compact.json"
    state_p.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(state_p.read_text())
    except Exception:
        state = {}
    sweep_scratch()          # clear spill orphaned by a previous crash
    print(f"lake_compact scheduler up: hourly=:15 daily=02:00 root={LAKE_ROOT} "
          f"raw={RAW_RET_D}d logs={LOG_RET_D}d rollup={ROLLUP_RET_D}d "
          f"max_bytes={LAKE_MAX_BYTES}", flush=True)
    while True:
        now = datetime.now(timezone.utc)
        for mode, key, due in (
            ("hourly", now.strftime("%Y-%m-%dT%H"), now.minute >= 15),
            ("daily", now.strftime("%Y-%m-%d"), now.hour >= 2),
        ):
            if due and state.get(mode) != key:
                t0 = time.time()
                try:
                    (run_daily if mode == "daily" else run_hourly)()
                    print(f"{mode} run {key} ok in {time.time()-t0:.1f}s", flush=True)
                except Exception as e:
                    print(f"WARN {mode} run {key}: {type(e).__name__}: {e}",
                          flush=True)
                # Mark even on failure: a poison partition must not hot-loop.
                state[mode] = key
                tmp = state_p.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(state))
                os.replace(tmp, state_p)
        time.sleep(60)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "hourly"
    if mode == "scheduler":
        run_scheduler()
    else:
        (run_daily if mode == "daily" else run_hourly)()
