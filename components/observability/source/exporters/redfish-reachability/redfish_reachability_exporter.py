#!/usr/bin/env python3
"""Low-pressure, unauthenticated Redfish reachability coverage exporter.

This collector intentionally requests only the public Redfish service root.  It
does not attempt credentials or sensor endpoints.  The exported series are
aggregated by SU to keep cardinality bounded.
"""

from __future__ import annotations

import argparse
import csv
import random
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


CLUSTER = "IREN_MKZ"
SENSOR_FAMILIES = ("fan", "temperature", "power", "sel", "leak")


def esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def load_targets(path: Path) -> list[tuple[str, str, str]]:
    targets: list[tuple[str, str, str]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["node", "su", "address"]:
            raise ValueError("targets CSV must have exactly: node,su,address")
        for row in reader:
            node, su, address = (row[k].strip() for k in reader.fieldnames)
            if not node or not su.startswith("SU") or not address:
                raise ValueError(f"invalid target row for {node or '<blank>'}")
            targets.append((node, su, address))
    if not targets:
        raise ValueError("targets CSV is empty")
    return targets


class Collector:
    def __init__(
        self,
        targets: list[tuple[str, str, str]],
        interval: float,
        timeout: float,
        concurrency: int,
    ) -> None:
        self.targets = targets
        self.interval = interval
        self.timeout = timeout
        self.concurrency = concurrency
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.started_at = time.time()
        self.sweep_in_progress = False
        self.sweep_progress = 0
        self.last_duration = 0.0
        self.last_completed = 0.0
        self.sweeps_total = 0
        self.reachable: Counter[str] = Counter()
        self.attempted: Counter[str] = Counter()
        self.current_reachable: Counter[str] = Counter()
        self.current_attempted: Counter[str] = Counter()
        self.context = ssl.create_default_context()
        self.context.check_hostname = False
        self.context.verify_mode = ssl.CERT_NONE

    def probe(self, target: tuple[str, str, str]) -> tuple[str, bool]:
        _, su, address = target
        request = urllib.request.Request(
            f"https://{address}/redfish/v1/",
            headers={"User-Agent": "nvis-redfish-reachability/1.0"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=self.context
            ) as response:
                # The service root is small.  Cap the read so a bad peer cannot
                # inflate site-management memory or network use.
                response.read(65536)
                return su, 200 <= response.status < 500
        except urllib.error.HTTPError as exc:
            # A 401/403 still proves that a Redfish HTTPS endpoint is present.
            return su, exc.code in (401, 403)
        except (OSError, TimeoutError, urllib.error.URLError):
            return su, False

    def run_sweep(self) -> None:
        targets = list(self.targets)
        random.shuffle(targets)
        started = time.monotonic()
        with self.lock:
            self.sweep_in_progress = True
            self.sweep_progress = 0
            self.current_reachable = Counter()
            self.current_attempted = Counter()

        # Submission spacing makes the normal request rate roughly uniform.
        # The fixed worker bound controls the failure/timeout case.
        spacing = self.interval / len(targets)
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = []
            next_submit = time.monotonic()
            for target in targets:
                if self.stop.is_set():
                    return
                delay = next_submit - time.monotonic()
                if delay > 0 and self.stop.wait(delay):
                    return
                future = pool.submit(self.probe, target)
                future.add_done_callback(self.record_result)
                futures.append(future)
                next_submit += spacing
            for future in futures:
                future.result()

        completed = time.time()
        with self.lock:
            self.reachable = self.current_reachable.copy()
            self.attempted = self.current_attempted.copy()
            self.last_duration = time.monotonic() - started
            self.last_completed = completed
            self.sweeps_total += 1
            self.sweep_in_progress = False

    def record_result(self, future) -> None:
        su, ok = future.result()
        with self.lock:
            self.current_attempted[su] += 1
            self.current_reachable[su] += int(ok)
            self.sweep_progress += 1

    def run(self) -> None:
        # A small startup jitter avoids synchronized restart bursts.
        if self.stop.wait(random.uniform(0.0, min(30.0, self.interval / 20.0))):
            return
        while not self.stop.is_set():
            started = time.monotonic()
            self.run_sweep()
            delay = max(1.0, self.interval - (time.monotonic() - started))
            self.stop.wait(delay)

    def render(self) -> str:
        totals = Counter(su for _, su, _ in self.targets)
        with self.lock:
            reachable = self.reachable.copy()
            attempted = self.attempted.copy()
            current_reachable = self.current_reachable.copy()
            current_attempted = self.current_attempted.copy()
            progress = self.sweep_progress
            in_progress = self.sweep_in_progress
            last_duration = self.last_duration
            last_completed = self.last_completed
            sweeps_total = self.sweeps_total
        labels = f'cluster="{esc(CLUSTER)}"'
        lines = [
            "# HELP nvis_redfish_reachability_targets Configured BMC targets by SU.",
            "# TYPE nvis_redfish_reachability_targets gauge",
        ]
        for su in sorted(totals, key=lambda x: int(x[2:])):
            sl = f'{labels},su="{esc(su)}"'
            lines.extend(
                (
                    f"nvis_redfish_reachability_targets{{{sl}}} {totals[su]}",
                    f"nvis_redfish_reachability_attempted{{{sl}}} {attempted[su]}",
                    f"nvis_redfish_reachability_reachable{{{sl}}} {reachable[su]}",
                    f"nvis_redfish_reachability_unreachable{{{sl}}} {max(0, attempted[su] - reachable[su])}",
                    f"nvis_redfish_reachability_current_attempted{{{sl}}} {current_attempted[su]}",
                    f"nvis_redfish_reachability_current_reachable{{{sl}}} {current_reachable[su]}",
                )
            )
        lines.extend(
            (
                "# HELP nvis_redfish_reachability_sweep_in_progress Whether a bounded reachability sweep is running.",
                "# TYPE nvis_redfish_reachability_sweep_in_progress gauge",
                f"nvis_redfish_reachability_sweep_in_progress{{{labels}}} {int(in_progress)}",
                f"nvis_redfish_reachability_sweep_progress{{{labels}}} {progress}",
                f"nvis_redfish_reachability_sweep_duration_seconds{{{labels}}} {last_duration:.6f}",
                f"nvis_redfish_reachability_last_completed_timestamp_seconds{{{labels}}} {last_completed:.3f}",
                f"nvis_redfish_reachability_sweeps_total{{{labels}}} {sweeps_total}",
                "# HELP nvis_redfish_credential_configured Whether an approved BMC credential is configured for sensor collection.",
                "# TYPE nvis_redfish_credential_configured gauge",
                f"nvis_redfish_credential_configured{{{labels}}} 0",
                "# HELP nvis_redfish_sensor_coverage_nodes Nodes supplying authenticated Redfish sensor metrics by family.",
                "# TYPE nvis_redfish_sensor_coverage_nodes gauge",
            )
        )
        for family in SENSOR_FAMILIES:
            lines.append(
                f'nvis_redfish_sensor_coverage_nodes{{{labels},family="{family}"}} 0'
            )
        lines.append("")
        return "\n".join(lines)


def make_handler(collector: Collector):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in ("/metrics", "/healthz"):
                self.send_error(404)
                return
            if self.path == "/healthz":
                body = b"ok\n"
                content_type = "text/plain; charset=utf-8"
            else:
                body = collector.render().encode()
                content_type = "text/plain; version=0.0.4; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9421)
    parser.add_argument("--interval", type=float, default=1800.0)
    parser.add_argument("--timeout", type=float, default=1.5)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if args.interval < 300 or not 0.1 <= args.timeout <= 5 or not 1 <= args.concurrency <= 8:
        parser.error("unsafe bounds: interval>=300, timeout=0.1..5, concurrency=1..8")
    collector = Collector(load_targets(args.targets), args.interval, args.timeout, args.concurrency)
    worker = threading.Thread(target=collector.run, name="redfish-sweep", daemon=True)
    worker.start()
    server = ThreadingHTTPServer((args.listen, args.port), make_handler(collector))
    try:
        server.serve_forever(poll_interval=1.0)
    finally:
        collector.stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
