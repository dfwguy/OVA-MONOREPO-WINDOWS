#!/usr/bin/env python3
"""
nvis-lake-fabric — pulls high-cardinality per-port PHY straight to Parquet,
keeping BER/FEC/optics OUT of the TSDB index while preserving full history.

Feeds fabric_phy:
  - IB     : ufm-telemetry open CSV  http://<UFM>:9001/csv/metrics
  - Eth    : LLDPq-Ethernet / Cumulus counters (JSON)   [wire per-site]
  - NVLink : nvlmapper raw-BER / down-lane dump          [wire per-site]

Only the IB CSV path is implemented concretely here (the one input we know the
shape of); eth/nvlink are stubs with the same landing call. 30s cadence.

Env: UFM_HOST, UFM_TELEMETRY_PORT(9001), POLL_SECONDS(30), CLUSTER_NAME.
"""
from __future__ import annotations
import csv
import io
import os
import time
import urllib.request

import pyarrow as pa

from lake_common import LakeSink, CLUSTER
from schema import FABRIC_SCHEMA

UFM_HOST = os.environ.get("UFM_HOST", "")
UFM_PORT = os.environ.get("UFM_TELEMETRY_PORT", "9001")
POLL = int(os.environ.get("POLL_SECONDS", "30"))

SINK = LakeSink()

# ufm CSV header -> our column (extend as the real header is confirmed)
_COL = {
    "Node_GUID": "switch_guid", "Port_Number": "port",
    "Raw_BER": "ber_raw", "Effective_BER": "ber_eff",
    "Symbol_Errors": "symbol_errors", "Temperature": "module_temp_c",
    "RX_Power": "rx_power_dbm", "TX_Power": "tx_power_dbm",
    "Link_Speed_Active": "link_speed", "Link_Width_Active": "link_width",
}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def poll_ib(now_us: int):
    if not UFM_HOST:
        return None
    url = f"http://{UFM_HOST}:{UFM_PORT}/csv/metrics"
    with urllib.request.urlopen(url, timeout=20) as r:
        text = r.read().decode("utf-8", "replace")
    rows = []
    for rec in csv.DictReader(io.StringIO(text)):
        row = {f.name: None for f in FABRIC_SCHEMA}
        row.update(ts=now_us, cluster=CLUSTER, plane="ib",
                   su="FABRIC", rack="ib-switch")
        for src, dst in _COL.items():
            if src in rec:
                row[dst] = _f(rec[src]) if dst not in (
                    "link_speed", "link_width") else rec[src]
        row["switch_guid"] = rec.get("Node_GUID")
        row["switch"] = rec.get("Node_Description") or rec.get("Node_GUID")
        try:
            row["port"] = int(rec.get("Port_Number") or 0)
        except ValueError:
            row["port"] = None
        rows.append(row)
    if not rows:
        return None
    cols = {f.name: [r.get(f.name) for r in rows] for f in FABRIC_SCHEMA}
    return pa.Table.from_pydict(cols, schema=FABRIC_SCHEMA)


def main():
    print(f"nvis-lake-fabric poll={POLL}s ufm={UFM_HOST or '<unset>'}", flush=True)
    while True:
        t0 = time.time()
        now_us = int(t0 * 1_000_000)
        try:
            tbl = poll_ib(now_us)
            if tbl is not None:
                SINK.add_table("fabric_phy", tbl)
        except Exception as e:
            print(f"poll error: {e}", flush=True)
        # eth/nvlink stubs land into the same table with plane=eth|nvlink
        time.sleep(max(1.0, POLL - (time.time() - t0)))


if __name__ == "__main__":
    main()
