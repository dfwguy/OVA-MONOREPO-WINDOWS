#!/usr/bin/env python3
"""Generate a sanitized node/SU/BMC-address CSV from Rack Status cache."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sqlite3
from pathlib import Path


HOST_RE = re.compile(r"^example50-dh(01|02)-([a-k])\d{2}-\d{2}$")


def su_for_node(node: str) -> str | None:
    match = HOST_RE.match(node)
    if not match:
        return None
    hall, row = match.groups()
    if hall == "02":
        return f"SU{ord(row) - ord('a') + 1}"
    if row in "abc":
        return f"SU{ord(row) - ord('a') + 12}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    database = f"file:{args.database}?mode=ro"
    with sqlite3.connect(database, uri=True) as conn:
        row = conn.execute(
            "SELECT payload_json FROM cluster_snapshots "
            "WHERE payload_json IS NOT NULL ORDER BY last_success_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        raise RuntimeError("no successful Rack Status snapshot")
    mapping = json.loads(row[0]).get("physical_rf0", {})
    targets = []
    for node, address in mapping.items():
        su = su_for_node(node)
        if su is not None:
            targets.append((node, su, str(address)))
    if len(targets) != 4032:
        raise RuntimeError(f"expected 4032 compute targets, found {len(targets)}")
    counts = {su: 0 for su in (f"SU{i}" for i in range(1, 15))}
    for _, su, _ in targets:
        counts[su] += 1
    if any(count != 288 for count in counts.values()):
        raise RuntimeError(f"unexpected per-SU counts: {counts}")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("node", "su", "address"))
    writer.writerows(sorted(targets))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".tmp")
    temp.write_text(buffer.getvalue(), encoding="utf-8")
    os.chmod(temp, 0o640)
    os.replace(temp, args.output)


if __name__ == "__main__":
    main()
