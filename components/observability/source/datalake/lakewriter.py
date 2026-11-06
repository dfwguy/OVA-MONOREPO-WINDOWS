#!/usr/bin/env python3
"""
nvis-lakewriter — Parquet data-lake writer for IREN_MKZ GB300.

Receives the SAME streams the metrics stack already produces (Prometheus
remote_write + Loki push), write-ahead-logs the raw body, then decodes and lands
partitioned Parquet on NVMe. Adds ZERO scrape load to the fleet and lives in a
failure domain fully decoupled from VictoriaMetrics.

Endpoints:
  POST /api/v1/write        Prometheus remote_write v1 (snappy WriteRequest pb)
  POST /loki/api/v1/push    Loki push (snappy PushRequest pb) OR JSON push
  POST /v1/artifacts        run-input capture, JSON (see lake_artifacts.py):
                            the conf/profile/sbatch/YAML files and synthesized
                            argv that DEFINED a run, verbatim + sha256, keyed by
                            run_id -> run_artifacts table
  GET  /metrics             self-observability (scraped -> Prometheus -> VM)
  GET  /healthz             liveness

Deps: pyarrow, python-snappy, protobuf (prometheus_pb2, loki logproto). If the
generated protobuf modules are absent, JSON fallbacks are used so the service
still starts (design/reference; wire the .proto stubs in the image build).

Env: LAKE_ROOT, CLUSTER_NAME, PORT(9410), WORKERS, SPOOL_MAX, MIN_FREE_BYTES,
FLUSH_BYTES, FLUSH_SECONDS. See datalake_parquet.md.
"""
from __future__ import annotations
import gzip
import json
import os
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pyarrow as pa

import pb_minimal
import lake_selfmetrics          # extended self-observability (installed in main())
import lake_artifacts            # run-artifact capture (POST /v1/artifacts)
from lake_common import LakeSink, IDENTITY, CLUSTER, LAKE_ROOT, LANDING
from schema import METRICS_SCHEMA, LOGS_SCHEMA

try:
    import snappy  # python-snappy
except Exception:
    snappy = None

PORT = int(os.environ.get("PORT", "9410"))
SPOOL = LAKE_ROOT / "raw_spool"
SPOOL_MAX = int(os.environ.get("SPOOL_MAX", str(50 * 1024 ** 3)))
MIN_FREE = int(os.environ.get("MIN_FREE_BYTES", str(200 * 1024 ** 3)))

# ---- self metrics ----------------------------------------------------------
_M = {"rows": {}, "bytes": {}, "flush_lag": {}, "dropped": {}, "last_write": {}}
_MLOCK = threading.Lock()


def _on_flush(table, rows, nbytes, lag):
    with _MLOCK:
        _M["rows"][table] = _M["rows"].get(table, 0) + rows
        _M["bytes"][table] = _M["bytes"].get(table, 0) + nbytes
        _M["flush_lag"][table] = lag
        _M["last_write"][table] = time.time()


SINK = LakeSink(on_flush=_on_flush)

# Arrow schemas are centralised in schema.py (single source of truth).


def _drop(reason, n=1):
    with _MLOCK:
        _M["dropped"][reason] = _M["dropped"].get(reason, 0) + n


def _spool_write(kind: bytes, body: bytes):
    """Write-ahead: append raw body to a spool segment before ACK."""
    SPOOL.mkdir(parents=True, exist_ok=True)
    seg = SPOOL / f"{kind.decode()}-{time.time_ns()}.seg"
    with open(seg, "wb") as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    return seg


def _free_one(p) -> int:
    """Free bytes on the filesystem backing p, or -1 if it cannot be measured."""
    try:
        return shutil.disk_usage(p).free
    except Exception:
        return -1


def _dev_of(p) -> int:
    """st_dev of the filesystem actually backing p (0 if unresolvable).

    Exposed as a metric so a STALE OR MISSING BIND MOUNT is detectable from
    /metrics alone. When /data/lake and /data/spool are correctly bound to the
    NVMe they share one st_dev that DIFFERS from the container root's; if a
    bind was created before the NVMe was mounted, they silently collapse onto
    the root filesystem's st_dev and the lake writes to the wrong disk while
    every other metric still looks healthy.
    """
    try:
        return os.stat(p).st_dev
    except Exception:
        return 0


def _free_bytes() -> int:
    """Free bytes on the filesystem(s) that actually receive lake writes.

    Parquet lands under LAKE_ROOT/landing while the write-ahead log lands in
    SPOOL, which is a SEPARATE bind mount (/data/spool -> /data/lake/raw_spool).
    Gating admission on LAKE_ROOT alone protects the wrong filesystem whenever
    the two resolve to different devices. Report the TIGHTER of the real write
    targets so admission control can never be fooled by a half-applied bind.
    """
    vals = [v for v in (_free_one(LANDING), _free_one(SPOOL), _free_one(LAKE_ROOT))
            if v >= 0]
    return min(vals) if vals else 0


def _spool_bytes() -> int:
    try:
        return sum(f.stat().st_size for f in SPOOL.glob("*.seg"))
    except Exception:
        return 0


# ---- decoders (protobuf preferred, JSON/labels fallback) -------------------
def _iter_write_request(raw: bytes):
    """(labels, samples[(ts_ms,value)]) per series — generated stub or pure-python."""
    try:
        import prometheus_pb2 as pb  # generated from prometheus remote.proto
        wr = pb.WriteRequest()
        wr.ParseFromString(raw)
        for ts_ser in wr.timeseries:
            yield ({l.name: l.value for l in ts_ser.labels},
                   [(s.timestamp, s.value) for s in ts_ser.samples])
    except ImportError:
        # no protoc needed — decode the wire format directly (primary feed).
        yield from pb_minimal.decode_write_request(raw)


def decode_remote_write(body: bytes):
    """Yield metric rows from a Prometheus WriteRequest (snappy pb)."""
    raw = snappy.uncompress(body) if snappy else body
    for lbls, samples in _iter_write_request(raw):
        lbls = dict(lbls)
        name = lbls.pop("__name__", "unknown")
        node = lbls.get("node") or lbls.get("Hostname") or lbls.get("instance", "")
        su, rack = IDENTITY.lookup(node, lbls)
        gpu = lbls.get("gpu") or lbls.get("GPU_I_ID")
        for ts_ms, value in samples:
            yield {
                "ts": int(ts_ms) * 1000,  # ms -> us
                "metric": name, "value": value, "cluster": CLUSTER,
                "su": su, "rack": rack, "node": node,
                "gpu": int(gpu) if gpu and str(gpu).isdigit() else None,
                "job": lbls.get("job"), "instance": lbls.get("instance"),
                "labels": {k: v for k, v in lbls.items()
                           if k not in ("job", "instance")},
            }


def decode_loki(body: bytes, content_type: str):
    """Yield log rows from a Loki push (snappy pb) or JSON push."""
    if "json" in (content_type or ""):
        data = json.loads(gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body)
        for st in data.get("streams", []):
            lbls = st.get("stream", {})
            node = lbls.get("node") or lbls.get("host", "")
            su, rack = IDENTITY.lookup(node, lbls)
            for ts_ns, line in st.get("values", []):
                yield _log_row(int(ts_ns) // 1000, node, su, rack, lbls, line)
        return
    raw = snappy.uncompress(body) if snappy else body
    try:
        import logproto_pb2 as lp
        pr = lp.PushRequest()
        pr.ParseFromString(raw)
        streams = [(st.labels,
                    [(e.timestamp.seconds * 1_000_000_000 + e.timestamp.nanos,
                      e.line) for e in st.entries]) for st in pr.streams]
    except ImportError:
        # no protoc needed — decode the wire format directly.
        streams = pb_minimal.decode_loki_push(raw)
    for labels_str, entries in streams:
        lbls = _parse_labelstring(labels_str)
        node = lbls.get("node") or lbls.get("host", "")
        su, rack = IDENTITY.lookup(node, lbls)
        for ts_ns, line in entries:
            yield _log_row(int(ts_ns) // 1000, node, su, rack, lbls, line)


def _otlp_attrs(attr_list) -> dict:
    """Flatten OTLP KeyValue list -> {key: str_value} (stringValue/intValue/…)."""
    out = {}
    for kv in attr_list or []:
        v = kv.get("value", {})
        out[kv.get("key", "")] = (
            v.get("stringValue") if "stringValue" in v else
            v.get("intValue") if "intValue" in v else
            v.get("boolValue") if "boolValue" in v else
            v.get("doubleValue"))
    return out


def decode_otlp_logs(body: bytes):
    """Yield log rows from an OTLP/HTTP logs export in JSON encoding.

    Fed by the running nvis-otel-collector (otelcol.exporter.otlphttp, json) or
    on-node Alloy otelcol.exporter.otlphttp -> POST /v1/logs. Protobuf OTLP is
    not parsed here (Alloy/otel can emit json); wire the pb path in the build if
    a binary OTLP exporter is used instead.
    """
    data = json.loads(gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body)
    for rl in data.get("resourceLogs", []):
        rattr = _otlp_attrs(rl.get("resource", {}).get("attributes"))
        node = (rattr.get("node") or rattr.get("host.name")
                or rattr.get("host") or "")
        su, rack = IDENTITY.lookup(node, lbls)
        for sl in rl.get("scopeLogs", []):
            for lr in sl.get("logRecords", []):
                lattr = _otlp_attrs(lr.get("attributes"))
                ts_ns = int(lr.get("timeUnixNano")
                            or lr.get("observedTimeUnixNano") or 0)
                line = (lr.get("body", {}) or {}).get("stringValue", "")
                lbls = {**rattr, **lattr,
                        "level": lr.get("severityText", ""),
                        "source": lattr.get("source") or rattr.get("source")
                        or "otel"}
                yield _log_row(ts_ns // 1000 if ts_ns else int(time.time() * 1e6),
                               node, su, rack, lbls, line)


def _parse_labelstring(s: str) -> dict:
    out = {}
    for part in s.strip("{}").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def _log_row(ts_us, node, su, rack, lbls, line):
    xid = None
    msg_class = None
    kv = {}
    low = line.lower()
    if "xid" in low:
        msg_class = "GPU_XID"
        for tok in line.replace(":", " ").split():
            if tok.isdigit():
                xid = int(tok); break
    elif "out of bounds" in low or "busbw" in low or "bus bandwidth" in low:
        msg_class = "NCCL_RESULT"
    elif "mnnvl" in low:
        msg_class = "MNNVL"
    elif "aer" in low or "pcieport" in low:
        msg_class = "PCIE_AER"
    elif "thermal" in low:
        msg_class = "THERMAL"
    return {
        "ts": ts_us, "cluster": CLUSTER, "su": su, "rack": rack, "node": node,
        "source": lbls.get("job") or lbls.get("source", "log"),
        "unit": lbls.get("unit") or lbls.get("systemd_unit", ""),
        "severity": lbls.get("level") or lbls.get("severity", ""),
        "xid": xid, "job": lbls.get("jobid"), "msg_class": msg_class,
        "kv": kv, "raw": line,
    }


def _rows_to_table(rows, schema):
    if not rows:
        return None
    cols = {f.name: [r.get(f.name) for r in rows] for f in schema}
    return pa.Table.from_pydict(cols, schema=schema)


# ---- HTTP ------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body=b""):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, b"ok")
        if self.path == "/metrics":
            return self._send(200, render_metrics().encode())
        self._send(404)

    def _ingest(self, kind, table, schema, rows_iter, ok_code):
        """WAL the raw body, decode+buffer, then delete the WAL segment.

        The spool segment is the crash-safety write-ahead record: it is fsync'd
        before we touch the decoder and unlinked only after the rows are safely
        in a partition buffer, so a mid-request kill leaves a replayable segment
        (see _replay_spool) and the spool never grows without bound.
        """
        seg = _spool_write(kind, self._body)
        t = _rows_to_table(list(rows_iter), schema)
        if t is not None:
            SINK.add_table(table, t)
        seg.unlink(missing_ok=True)
        return self._send(ok_code)

    def _ingest_artifacts(self, body: bytes):
        """POST /v1/artifacts — verbatim run-input capture (run_artifacts table).

        Deliberately NOT routed through _ingest():
          * no WAL segment — the parquet write is synchronous and atomic
            (tmp -> os.replace), so we only ACK once the bytes are ON DISK.
            The metrics path ACKs when rows reach an in-memory buffer, which
            costs it a FLUSH_SECONDS crash window; provenance cannot afford one.
          * errors are NOT swallowed into a 200. A remote_write sender that gets
            a 200 for a batch we dropped just loses a sample; an artifact sender
            that gets a 200 for a rejected push believes a run is reproducible
            when it is not. 400 = the client's payload is bad (bad run_id,
            sha256 mismatch); 500 = ours.
        """
        hdr = self.headers.get("X-Lake-Inline-Max")
        inline_max = int(hdr) if hdr and hdr.isdigit() else None
        payload = None
        try:
            data = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise lake_artifacts.ArtifactError("payload must be a JSON object")
            rows, nbytes, paths, skipped = lake_artifacts.ingest_payload(
                payload, inline_max)
        except (lake_artifacts.ArtifactError, json.JSONDecodeError,
                UnicodeDecodeError, OSError) as e:
            # A bad payload is the CLIENT's bug: say 400 so the sender fixes it
            # and knows the provenance record was not written. Anything else
            # falls through to do_POST's 500.
            _drop("artifact_reject")
            return self._send(400, json.dumps(
                {"error": f"{type(e).__name__}: {e}"}).encode())
        if rows:
            # reuse the flush accounting so run_artifacts shows up in the
            # existing nvis_lake_rows_written_total{table=...} exposition.
            _on_flush("run_artifacts", rows, nbytes, 0.0)
        if skipped:
            _drop("artifact_duplicate", skipped)
        return self._send(200, json.dumps({
            "status": "ok", "table": "run_artifacts",
            "run_id": payload.get("run_id"), "rows": rows, "bytes": nbytes,
            "skipped_duplicate": skipped,
            "files": [str(p) for p in paths]}).encode())

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self._body = self.rfile.read(n) if n else b""
        body = self._body
        # admission control — protect NVMe & bound spool; VM path is untouched
        if _spool_bytes() > SPOOL_MAX or _free_bytes() < MIN_FREE:
            _drop("admission_429")
            return self._send(429, b"lake backpressure")
        if self.path == "/v1/artifacts":       # run-input capture (provenance)
            try:
                return self._ingest_artifacts(body)
            except Exception as e:
                _drop(f"artifact_err:{type(e).__name__}")
                return self._send(500, json.dumps(
                    {"error": f"{type(e).__name__}: {e}"}).encode())
        try:
            if self.path == "/api/v1/write":
                return self._ingest(b"m", "metrics", METRICS_SCHEMA,
                                    decode_remote_write(body), 200)
            if self.path.startswith("/loki/api/v1/push"):
                ct = self.headers.get("Content-Type", "")
                return self._ingest(b"l", "logs", LOGS_SCHEMA,
                                    decode_loki(body, ct), 204)
            if self.path == "/v1/logs":            # OTLP/HTTP logs (json) from otel
                return self._ingest(b"o", "logs", LOGS_SCHEMA,
                                    decode_otlp_logs(body), 200)
        except Exception as e:  # never 5xx-loop the sender; count and move on
            _drop(f"decode_err:{type(e).__name__}")
            return self._send(200)
        self._send(404)


def render_metrics() -> str:
    out = ["# nvis-lakewriter self metrics", "nvis_lake_up 1"]
    with _MLOCK:
        for t, v in _M["rows"].items():
            out.append(f'nvis_lake_rows_written_total{{table="{t}"}} {v}')
        for t, v in _M["bytes"].items():
            out.append(f'nvis_lake_bytes_written_total{{table="{t}"}} {v}')
        for t, v in _M["flush_lag"].items():
            out.append(f'nvis_lake_flush_lag_seconds{{table="{t}"}} {v:.3f}')
        for t, v in _M["last_write"].items():
            out.append(f'nvis_lake_partition_last_write_timestamp{{table="{t}"}} {v:.0f}')
        for r, v in _M["dropped"].items():
            out.append(f'nvis_lake_dropped_total{{reason="{r}"}} {v}')
    out.append(f"nvis_lake_spool_bytes {_spool_bytes()}")
    out.append(f"nvis_lake_nvme_free_bytes {_free_bytes()}")
    # Per-target free space and device identity. "blank never means healthy":
    # nvis_lake_fs_device{path="landing"} == nvis_lake_fs_device{path="rootfs"}
    # means the /data bind is stale and the lake is writing to the root LV.
    out.append(f'nvis_lake_fs_free_bytes{{path="landing"}} {_free_one(LANDING)}')
    out.append(f'nvis_lake_fs_free_bytes{{path="spool"}} {_free_one(SPOOL)}')
    out.append(f'nvis_lake_fs_device{{path="landing"}} {_dev_of(LANDING)}')
    out.append(f'nvis_lake_fs_device{{path="spool"}} {_dev_of(SPOOL)}')
    out.append(f'nvis_lake_fs_device{{path="rootfs"}} {_dev_of("/")}')
    return "\n".join(out) + "\n"


def _replay_spool():
    """Re-ingest WAL segments left by a crash mid-request, then remove them.

    Segment name prefix encodes the source: m=remote_write, l=loki-push,
    o=OTLP-logs. This is the crash-recovery half of the write-ahead scheme.
    """
    for seg in sorted(SPOOL.glob("*.seg")):
        try:
            body = seg.read_bytes()
            kind = seg.name[0]
            if kind == "m":
                t = _rows_to_table(list(decode_remote_write(body)), METRICS_SCHEMA)
            elif kind == "o":
                t = _rows_to_table(list(decode_otlp_logs(body)), LOGS_SCHEMA)
            else:  # loki push (protobuf/snappy default)
                t = _rows_to_table(list(decode_loki(body, "")), LOGS_SCHEMA)
            if t is not None:
                SINK.add_table("metrics" if kind == "m" else "logs", t)
            print(f"replayed spool segment {seg.name}", flush=True)
        except Exception as e:
            _drop(f"replay_err:{type(e).__name__}")
        finally:
            seg.unlink(missing_ok=True)


def main():
    # Extended self-observability. Wraps render_metrics/on_flush/Handler._send by
    # monkeypatch (no edits to the code above) so the exposition zero-initialises
    # every series this writer can produce — an ABSENT counter cannot be alerted
    # on, which is why 3 days of writing nothing looked healthy. See
    # lake_selfmetrics.py for the fault-to-metric mapping.
    lake_selfmetrics.install(sys.modules[__name__])
    # Materialise the full lake layout so every write target and every statvfs
    # probe resolves against a real directory on the NVMe rather than silently
    # falling back to a parent on another filesystem.
    for d in (LANDING, LAKE_ROOT / "curated", LAKE_ROOT / "_identity",
              LAKE_ROOT / "_state", SPOOL):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"WARN cannot create {d}: {e}", flush=True)
    _replay_spool()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"nvis-lakewriter listening :{PORT} root={LAKE_ROOT} cluster={CLUSTER}",
          flush=True)
    # Startup assertion: log the device each write target landed on. If landing
    # or spool share the rootfs device the /data bind did not apply.
    print(f"lake fs: landing dev={_dev_of(LANDING)} free={_free_one(LANDING)} "
          f"spool dev={_dev_of(SPOOL)} free={_free_one(SPOOL)} "
          f"rootfs dev={_dev_of('/')}", flush=True)
    if _dev_of(LANDING) == _dev_of("/") or _dev_of(SPOOL) == _dev_of("/"):
        print("WARN lake write target is on the ROOT filesystem — the /data "
              "bind mount is stale or missing; recreate this container",
              flush=True)
    try:
        srv.serve_forever()
    finally:
        SINK.stop()


if __name__ == "__main__":
    main()
