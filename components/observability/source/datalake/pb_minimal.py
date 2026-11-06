#!/usr/bin/env python3
"""
pb_minimal.py — dependency-free protobuf *wire* decoders for the two inbound
streams the lake receives: Prometheus remote_write v1 (`WriteRequest`) and Loki
push (`PushRequest`).

Why this exists: the writer's PRIMARY feed is Prometheus remote_write (binary
protobuf). Generating `prometheus_pb2` / `logproto_pb2` needs `protoc` in the
image build; until that exists the binary paths would otherwise drop 100% of the
metrics feed. These hand-rolled wire readers decode exactly the fields we need
with the stdlib only, so the service ingests the real feeds with zero build step.
`lakewriter.py` still prefers generated stubs when present and falls back here.

Only the field numbers actually used are parsed; unknown fields are skipped by
the generic wire walker, so this is forward-compatible with newer proto fields.

Wire reference:
  Prometheus remote.proto
    WriteRequest { repeated TimeSeries timeseries = 1; }
    TimeSeries   { repeated Label labels = 1; repeated Sample samples = 2; }
    Label        { string name = 1; string value = 2; }
    Sample       { double value = 1 (fixed64); int64 timestamp = 2 (varint, ms); }
  Loki logproto.proto
    PushRequest   { repeated StreamAdapter streams = 1; }
    StreamAdapter { string labels = 1; repeated EntryAdapter entries = 2; }
    EntryAdapter  { google.protobuf.Timestamp timestamp = 1; string line = 2; }
    Timestamp     { int64 seconds = 1; int32 nanos = 2; }
"""
from __future__ import annotations
import struct

WT_VARINT, WT_64BIT, WT_LEN, WT_32BIT = 0, 1, 2, 5


def _read_varint(buf: bytes, pos: int):
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def _iter_fields(buf: bytes, pos: int = 0, end: int | None = None):
    """Yield (field_number, wire_type, value) walking a protobuf message.

    value is: an int (varint), or bytes (len-delimited / 64bit / 32bit slice).
    Unknown fields are yielded too and simply ignored by callers.
    """
    if end is None:
        end = len(buf)
    while pos < end:
        tag, pos = _read_varint(buf, pos)
        field = tag >> 3
        wt = tag & 7
        if wt == WT_VARINT:
            val, pos = _read_varint(buf, pos)
        elif wt == WT_64BIT:
            val = buf[pos:pos + 8]
            pos += 8
        elif wt == WT_LEN:
            ln, pos = _read_varint(buf, pos)
            val = buf[pos:pos + ln]
            pos += ln
        elif wt == WT_32BIT:
            val = buf[pos:pos + 4]
            pos += 4
        else:  # groups (3/4) are not used by either proto
            raise ValueError(f"unsupported wire type {wt} at {pos}")
        yield field, wt, val


# ---- Prometheus WriteRequest ----------------------------------------------
def decode_write_request(raw: bytes):
    """Yield (labels: dict[str,str], samples: list[(ts_ms:int, value:float)])."""
    for field, wt, val in _iter_fields(raw):
        if field == 1 and wt == WT_LEN:      # timeseries
            yield _decode_timeseries(val)


def _decode_timeseries(buf: bytes):
    labels: dict[str, str] = {}
    samples: list[tuple[int, float]] = []
    for field, wt, val in _iter_fields(buf):
        if field == 1 and wt == WT_LEN:      # Label
            name = value = None
            for lf, _lwt, lval in _iter_fields(val):
                if lf == 1:
                    name = lval.decode("utf-8", "replace")
                elif lf == 2:
                    value = lval.decode("utf-8", "replace")
            if name is not None:
                labels[name] = value or ""
        elif field == 2 and wt == WT_LEN:    # Sample
            sval = 0.0
            sts = 0
            for sf, swt, sv in _iter_fields(val):
                if sf == 1 and swt == WT_64BIT:
                    sval = struct.unpack("<d", sv)[0]
                elif sf == 2 and swt == WT_VARINT:
                    sts = sv               # milliseconds since epoch
            samples.append((sts, sval))
    return labels, samples


# ---- Loki PushRequest ------------------------------------------------------
def decode_loki_push(raw: bytes):
    """Yield (labels_str: str, entries: list[(ts_ns:int, line:str)])."""
    for field, wt, val in _iter_fields(raw):
        if field == 1 and wt == WT_LEN:      # StreamAdapter
            yield _decode_stream(val)


def _decode_stream(buf: bytes):
    labels = ""
    entries: list[tuple[int, str]] = []
    for field, wt, val in _iter_fields(buf):
        if field == 1 and wt == WT_LEN:      # labels string
            labels = val.decode("utf-8", "replace")
        elif field == 2 and wt == WT_LEN:    # EntryAdapter
            ts_ns = 0
            line = ""
            for ef, ewt, ev in _iter_fields(val):
                if ef == 1 and ewt == WT_LEN:        # Timestamp message
                    secs = nanos = 0
                    for tf, _twt, tv in _iter_fields(ev):
                        if tf == 1:
                            secs = tv
                        elif tf == 2:
                            nanos = tv
                    ts_ns = secs * 1_000_000_000 + nanos
                elif ef == 2 and ewt == WT_LEN:      # line
                    line = ev.decode("utf-8", "replace")
            entries.append((ts_ns, line))
    return labels, entries
