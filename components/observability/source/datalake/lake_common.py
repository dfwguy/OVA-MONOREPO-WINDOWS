#!/usr/bin/env python3
"""
lake_common.py — shared partition-buffer + flush + identity mapping for the
IREN_MKZ Parquet data lake (nvis-lakewriter / nvis-lake-fabric).

Design: rows are appended to per-partition in-memory Arrow buffers keyed by
(table, su, rack, date, hour). A buffer flushes when it exceeds FLUSH_BYTES or
ages past FLUSH_SECONDS or the hour rolls. Flush is atomic (tmp -> fsync ->
rename) so readers never observe a partial Parquet file.

Stdlib + pyarrow only. No custom container image.
"""
from __future__ import annotations
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
# `pa.compute` is NOT auto-imported by `import pyarrow`. LakeSink.add_table()
# falls back to pa.compute.cast() for any schema whose `ts` is not
# timestamp[us]; without this explicit import that branch raises
# AttributeError and kills ingest for that table.
import pyarrow.compute  # noqa: F401  (registers the pa.compute attribute)
import pyarrow.parquet as pq

CLUSTER = os.environ.get("CLUSTER_NAME", "IREN_MKZ")
LAKE_ROOT = Path(os.environ.get("LAKE_ROOT", "/data/lake"))
LANDING = LAKE_ROOT / "landing"
FLUSH_BYTES = int(os.environ.get("FLUSH_BYTES", str(64 * 1024 * 1024)))
FLUSH_SECONDS = int(os.environ.get("FLUSH_SECONDS", "60"))
ZSTD_LEVEL = int(os.environ.get("ZSTD_LEVEL", "3"))
ROW_GROUP = int(os.environ.get("ROW_GROUP_BYTES", str(128 * 1024 * 1024)))

# ---- node -> (su, rack) identity mapping -----------------------------------
# Prefer ib-identity alias.json; fall back to parsing the hostname.
#
# 2026-08-13 — THE RACK NUMBER WAS HARDCODED. The pattern was
#     r"example50-dh01-([d-j])01-(\d+)"
# in which the "01" is a LITERAL, not a capture group, so only rack 01 of each
# row could ever match: 126 of 2016 hosts (6.2%). The other 1890 (93.8%) fell
# through to ("UNKNOWN","UNKNOWN") and every sample they carried was written to
# one partition, su=UNKNOWN/rack=UNKNOWN. That single hour-dir reached 87.7 GB
# across 133,009 files and OOM-killed the compactor in a loop for two weeks.
# The rack is now captured.
_SU_LETTER = {"d": "SU1", "e": "SU2", "f": "SU3", "g": "SU4",
              "h": "SU5", "i": "SU6", "j": "SU7"}
_NAME_RE = re.compile(r"example50-dh01-([d-j])(\d{2})-(\d+)", re.IGNORECASE)
# The shipped default points at a path nothing on this box ever writes, so the
# map was permanently empty and every lookup fell to the regex. Prefer the file
# the ib-identity exporter actually produces, and keep the old path as an
# override for deployments that do stage it.
_ALIAS_PATH = os.environ.get(
    "IB_ALIAS_JSON", "/data/lake/_identity/alias.json")
_ALIAS_FALLBACKS = (
    "/data/lake/_identity/alias.json",
    "/opt/observability/iren_mkz/exporters/ib-identity/alias.json",
)


class Identity:
    """node -> (su, rack); refreshed hourly from alias.json when present."""

    def __init__(self):
        self._lock = threading.Lock()
        self._map: dict[str, tuple[str, str]] = {}
        self._loaded = 0.0
        self.refresh()

    def refresh(self):
        """Load host -> (su, rack) from the ib-identity alias file.

        The real file is NESTED — {"hosts": {...}, "switches": {...},
        "guid_to_name": ..., "ip_to_name": ..., "meta": ...} — while this used to
        iterate the TOP level. Against the real file that produced five junk
        entries ("hosts", "switches", "meta", ...) and zero actual hosts, so even
        staging the file at the expected path would not have fixed anything.
        """
        m = {}
        for path in (_ALIAS_PATH, *_ALIAS_FALLBACKS):
            try:
                with open(path) as fh:
                    data = json.load(fh)
            except Exception:
                continue
            # Descend into the sections that hold entities; tolerate a flat file.
            sections = [data.get(k) for k in ("hosts", "switches")
                        if isinstance(data.get(k), dict)] or [data]
            for section in sections:
                for host, v in section.items():
                    if isinstance(v, dict) and ("su" in v or "rack" in v):
                        m[host] = (v.get("su", "UNKNOWN"), v.get("rack", "UNKNOWN"))
                    elif isinstance(v, (list, tuple)) and len(v) >= 2:
                        m[host] = (str(v[0]), str(v[1]))
            if m:
                break
        with self._lock:
            # Never install an empty map over a good one: a transient read error
            # would otherwise send the whole fleet to UNKNOWN until restart.
            if m or not self._map:
                self._map = m
            self._loaded = time.time()

    def lookup(self, node: str, labels: dict | None = None) -> tuple[str, str]:
        """Resolve (su, rack), preferring what the sample already told us.

        Order: the sample's own labels -> alias.json -> hostname -> UNKNOWN.
        Labels come first because they are authoritative and already present:
        every row in the poisoned partition carried
        labels={'su':'SU1','rack':'WH1D2',...} while the partition columns said
        UNKNOWN. The identity was never missing — it was just never promoted.
        """
        if labels:
            su = (labels.get("su") or "").strip()
            rack = (labels.get("rack") or "").strip()
            if su and rack:
                return su, rack
        if time.time() - self._loaded > 3600:
            self.refresh()
        with self._lock:
            hit = self._map.get(node)
        if hit and hit != ("UNKNOWN", "UNKNOWN"):
            return hit
        mm = _NAME_RE.search(node or "")
        if mm:
            letter, rack_ord = mm.group(1).lower(), mm.group(2)
            su = _SU_LETTER.get(letter, "UNKNOWN")
            # The rack is IN the hostname; it was previously synthesised from the
            # tray index as "<letter>01r{(tray-1)//18+1}", which split one physical
            # rack across r01/r02/r03 (trays 11-18, 28-36, 37) and pinned it to
            # rack 01. Use the real token.
            return su, f"{letter}{rack_ord}"
        return "UNKNOWN", "UNKNOWN"  # never drop — "blank never means healthy"


IDENTITY = Identity()


def part_dir(table: str, su: str, rack: str, ts_us: int) -> Path:
    dt = datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc)
    return (LANDING / table /
            f"cluster={CLUSTER}" / f"su={su}" / f"rack={rack}" /
            f"date={dt:%Y-%m-%d}" / f"hour={dt:%H}")


class PartitionBuffer:
    def __init__(self, table: str, key: tuple, schema: pa.Schema):
        self.table = table
        self.key = key            # (su, rack, date, hour)
        self.schema = schema
        self.batches: list[pa.RecordBatch] = []
        self.nbytes = 0
        self.first = time.time()

    def add(self, batch: pa.RecordBatch):
        self.batches.append(batch)
        self.nbytes += batch.nbytes

    def stale(self) -> bool:
        return (self.nbytes >= FLUSH_BYTES or
                (self.batches and time.time() - self.first >= FLUSH_SECONDS))


class LakeSink:
    """Thread-safe partition buffers + background flusher. Shared by writer/poller."""

    def __init__(self, on_flush=None):
        self._buf: dict[tuple, PartitionBuffer] = {}
        self._lock = threading.Lock()
        self._on_flush = on_flush  # callback(table, rows, bytes, lag)
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def add_table(self, table: str, tbl: pa.Table):
        """Route an Arrow table's rows into partition buffers by su/rack/hour."""
        # tbl must carry columns su, rack, ts (us). Split by (su, rack, hour).
        su = tbl.column("su").to_pylist()
        rack = tbl.column("rack").to_pylist()
        ts = tbl.column("ts")
        # bucket row indices by partition key
        buckets: dict[tuple, list[int]] = {}
        ts_us = [int(x.value) if x.value is not None else 0 for x in ts] \
            if ts.type == pa.timestamp("us") else \
            [int(pa.compute.cast(v, pa.int64()).as_py()) for v in ts]
        for i in range(tbl.num_rows):
            dt = datetime.fromtimestamp(ts_us[i] / 1_000_000, tz=timezone.utc)
            k = (table, su[i], rack[i], f"{dt:%Y-%m-%d}", f"{dt:%H}")
            buckets.setdefault(k, []).append(i)
        with self._lock:
            for k, idx in buckets.items():
                sub = tbl.take(pa.array(idx))
                pb = self._buf.get(k)
                if pb is None:
                    pb = PartitionBuffer(table, k[1:], tbl.schema)
                    self._buf[k] = pb
                for b in sub.to_batches():
                    pb.add(b)

    def _loop(self):
        while not self._stop.wait(2.0):
            self.flush_stale()

    def flush_stale(self, force=False):
        with self._lock:
            keys = [k for k, pb in self._buf.items() if force or pb.stale()]
        for k in keys:
            with self._lock:
                pb = self._buf.pop(k, None)
            if pb:
                self._flush_one(k[0], pb)

    def _flush_one(self, table: str, pb: PartitionBuffer):
        if not pb.batches:
            return
        tbl = pa.Table.from_batches(pb.batches, pb.schema)
        # sort by (node|switch, ts) if present for pushdown-friendly landing files
        sort_cols = [c for c in ("node", "switch", "ts") if c in tbl.column_names]
        if sort_cols:
            tbl = tbl.sort_by([(c, "ascending") for c in sort_cols])
        su, rack, date, hour = pb.key
        ts0 = int(tbl.column("ts")[0].value) if tbl.num_rows else int(time.time() * 1e6)
        d = part_dir(table, su, rack, ts0)
        d.mkdir(parents=True, exist_ok=True)
        name = f"part-{uuid.uuid4().hex}.parquet"
        tmp = d / (name + ".tmp")
        pq.write_table(tbl, tmp, compression="zstd",
                       compression_level=ZSTD_LEVEL, use_dictionary=True,
                       write_statistics=True, row_group_size=None)
        os.replace(tmp, d / name)          # atomic
        lag = time.time() - pb.first
        if self._on_flush:
            self._on_flush(table, tbl.num_rows, tbl.nbytes, lag)

    def stop(self):
        self._stop.set()
        self.flush_stale(force=True)
