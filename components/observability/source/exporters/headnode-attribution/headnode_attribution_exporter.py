#!/usr/bin/env python3
"""Low-overhead per-user and systemd-service resource attribution exporter.

Privacy contract: reads /proc/<pid>/comm and numeric counters only. It never
reads process command lines, environments, open files, or network payloads.
"""

from __future__ import annotations

import glob
import os
import pwd
import re
import socket
import subprocess
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("ATTRIBUTION_EXPORTER_PORT", "9106"))
HOST = os.environ.get("ATTRIBUTION_EXPORTER_HOST", "0.0.0.0")
CLUSTER = os.environ.get("CLUSTER_NAME", "IREN_MKZ")
NODE = os.environ.get("NODE_NAME", socket.gethostname().split(".")[0])
ROLE = os.environ.get("NODE_ROLE", "head")
PRIMARY_IPV4 = os.environ.get("PRIMARY_IPV4", "192.0.2.4")
PLATFORM = os.environ.get("PLATFORM_NAME", "slurm-bcm-control-plane")
HZ = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
PAGE = os.sysconf("SC_PAGE_SIZE")
NCPU = os.cpu_count() or 1


def esc(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def labels(**items: object) -> str:
    base = {"cluster": CLUSTER, "node": NODE, "role": ROLE}
    base.update(items)
    return "{" + ",".join(f'{key}="{esc(value)}"' for key, value in sorted(base.items())) + "}"


def metric(lines: list[str], name: str, value: float | int, **labs: object) -> None:
    lines.append(f"{name}{labels(**labs)} {value}")


def read_number(path: str, default: int = 0) -> int:
    try:
        with open(path, encoding="ascii") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return default


def username(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def proc_snapshot() -> dict[tuple[int, int], dict[str, object]]:
    result: dict[tuple[int, int], dict[str, object]] = {}
    for path in glob.glob("/proc/[0-9]*/stat"):
        try:
            pid = int(path.split("/")[2])
            raw = open(path, encoding="utf-8", errors="replace").read()
            left, right = raw.find("("), raw.rfind(")")
            if left < 0 or right < left:
                continue
            comm = raw[left + 1:right][:80]
            fields = raw[right + 2:].split()
            uid = os.stat(f"/proc/{pid}").st_uid
            start = int(fields[19])
            cpu = (int(fields[11]) + int(fields[12])) / HZ
            threads = int(fields[17])
            rss = max(0, int(fields[21])) * PAGE
            read_bytes = write_bytes = 0
            try:
                with open(f"/proc/{pid}/io", encoding="ascii") as io_handle:
                    for line in io_handle:
                        key, _, val = line.partition(":")
                        if key == "read_bytes":
                            read_bytes = int(val)
                        elif key == "write_bytes":
                            write_bytes = int(val)
            except (OSError, ValueError):
                pass
            result[(pid, start)] = {
                "user": username(uid), "uid": uid, "comm": comm, "cpu": cpu,
                "threads": threads, "rss": rss, "read": read_bytes, "write": write_bytes,
            }
        except (OSError, ValueError, IndexError):
            continue
    return result


def decode_unit(value: str) -> str:
    return re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), value)


def service_snapshot() -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for path in glob.glob("/sys/fs/cgroup/system.slice/*.service"):
        unit = decode_unit(os.path.basename(path))
        usage = 0
        try:
            with open(os.path.join(path, "cpu.stat"), encoding="ascii") as handle:
                for line in handle:
                    key, value = line.split()[:2]
                    if key == "usage_usec":
                        usage = int(value)
                        break
        except (OSError, ValueError):
            pass
        rbytes = wbytes = 0
        try:
            with open(os.path.join(path, "io.stat"), encoding="ascii") as handle:
                for line in handle:
                    for item in line.split()[1:]:
                        key, _, value = item.partition("=")
                        if key == "rbytes":
                            rbytes += int(value)
                        elif key == "wbytes":
                            wbytes += int(value)
        except (OSError, ValueError):
            pass
        result[unit] = {
            "cpu_usec": usage,
            "memory": read_number(os.path.join(path, "memory.current")),
            "tasks": read_number(os.path.join(path, "pids.current")),
            "read": rbytes,
            "write": wbytes,
        }
    return result


def login_sessions() -> dict[str, int]:
    sessions: dict[str, int] = defaultdict(int)
    try:
        proc = subprocess.run(["/usr/bin/who"], capture_output=True, text=True, timeout=3, check=False)
        for line in proc.stdout.splitlines():
            fields = line.split()
            if fields:
                sessions[fields[0]] += 1
    except (OSError, subprocess.TimeoutExpired):
        pass
    return sessions


def failed_services() -> list[str]:
    try:
        proc = subprocess.run(
            ["/usr/bin/systemctl", "--failed", "--type=service", "--no-legend", "--plain", "--no-pager"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return [line.split()[0] for line in proc.stdout.splitlines() if line.split() and line.split()[0].endswith(".service")]
    except (OSError, subprocess.TimeoutExpired):
        return []


def tcp_listener_up(host: str, port: int) -> int:
    """Bounded unauthenticated reachability check; sends no application data."""
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return 1
    except OSError:
        return 0


class Collector:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.previous_time = time.monotonic()
        self.previous_proc: dict[tuple[int, int], dict[str, object]] = {}
        self.previous_services: dict[str, dict[str, int]] = {}

    def collect(self) -> str:
        with self.lock:
            started = time.time()
            now = time.monotonic()
            elapsed = max(0.001, now - self.previous_time)
            procs = proc_snapshot()
            services = service_snapshot()
            sessions = login_sessions()
            failed = failed_services()
            users: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
            commands: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
            for key, item in procs.items():
                user, comm = str(item["user"]), str(item["comm"])
                old = self.previous_proc.get(key)
                cpu_pct = max(0.0, float(item["cpu"]) - float(old["cpu"])) * 100.0 / elapsed if old else 0.0
                read_bps = max(0.0, int(item["read"]) - int(old["read"])) / elapsed if old else 0.0
                write_bps = max(0.0, int(item["write"]) - int(old["write"])) / elapsed if old else 0.0
                for bucket in (users[user], commands[(user, comm)]):
                    bucket["cpu"] += cpu_pct
                    bucket["rss"] += int(item["rss"])
                    bucket["processes"] += 1
                    bucket["threads"] += int(item["threads"])
                    bucket["read"] += read_bps
                    bucket["write"] += write_bps

            lines = [
                "# HELP headnode_user_resource_score Weighted measured host-resource share (50% CPU, 40% memory, 10% disk I/O).",
                "# TYPE headnode_user_resource_score gauge",
                "# HELP headnode_user_cpu_percent User CPU consumption; 100 percent equals one logical CPU.",
                "# TYPE headnode_user_cpu_percent gauge",
            ]
            mem_total = 1
            try:
                with open("/proc/meminfo", encoding="ascii") as handle:
                    for line in handle:
                        if line.startswith("MemTotal:"):
                            mem_total = int(line.split()[1]) * 1024
                            break
            except OSError:
                pass
            for user, values in users.items():
                try:
                    account = pwd.getpwnam(user)
                    login_shell = account.pw_shell not in ("", "/usr/sbin/nologin", "/sbin/nologin", "/bin/false")
                    kind = "interactive" if account.pw_uid >= 1000 and login_shell else "system"
                except KeyError:
                    kind = "unknown"
                cpu_share = values["cpu"] / NCPU
                memory_share = 100.0 * values["rss"] / max(1, mem_total)
                io_share = min(100.0, 100.0 * (values["read"] + values["write"]) / 100_000_000.0)
                score = 0.50 * cpu_share + 0.40 * memory_share + 0.10 * io_share
                metric(lines, "headnode_user_resource_score", score, user=user, account_type=kind)
                metric(lines, "headnode_user_cpu_percent", values["cpu"], user=user, account_type=kind)
                metric(lines, "headnode_user_rss_bytes", values["rss"], user=user, account_type=kind)
                metric(lines, "headnode_user_process_count", values["processes"], user=user, account_type=kind)
                metric(lines, "headnode_user_thread_count", values["threads"], user=user, account_type=kind)
                metric(lines, "headnode_user_io_read_bytes_per_second", values["read"], user=user, account_type=kind)
                metric(lines, "headnode_user_io_write_bytes_per_second", values["write"], user=user, account_type=kind)
                metric(lines, "headnode_user_login_sessions", sessions.get(user, 0), user=user, account_type=kind)
            for user, count in sessions.items():
                if user not in users:
                    metric(lines, "headnode_user_login_sessions", count, user=user, account_type="interactive")
            for (user, comm), values in commands.items():
                metric(lines, "headnode_proc_cpu_percent", values["cpu"], user=user, comm=comm)
                metric(lines, "headnode_proc_rss_bytes", values["rss"], user=user, comm=comm)
                metric(lines, "headnode_proc_count", values["processes"], user=user, comm=comm)
                metric(lines, "headnode_proc_threads", values["threads"], user=user, comm=comm)

            for unit, values in services.items():
                old = self.previous_services.get(unit)
                cpu_pct = max(0.0, values["cpu_usec"] - old["cpu_usec"]) / 1_000_000 * 100 / elapsed if old else 0.0
                read_bps = max(0.0, values["read"] - old["read"]) / elapsed if old else 0.0
                write_bps = max(0.0, values["write"] - old["write"]) / elapsed if old else 0.0
                metric(lines, "headnode_service_cpu_percent", cpu_pct, service=unit)
                metric(lines, "headnode_service_memory_bytes", values["memory"], service=unit)
                metric(lines, "headnode_service_tasks", values["tasks"], service=unit)
                metric(lines, "headnode_service_io_read_bytes_per_second", read_bps, service=unit)
                metric(lines, "headnode_service_io_write_bytes_per_second", write_bps, service=unit)
                metric(lines, "headnode_service_active", 1, service=unit)

            metric(lines, "headnode_logged_in_sessions", sum(sessions.values()))
            metric(lines, "headnode_systemd_failed_units", len(failed))
            for unit in failed:
                metric(lines, "headnode_service_failed", 1, service=unit)
            metric(lines, "headnode_attribution_exporter_up", 1)
            metric(lines, "headnode_attribution_exporter_last_success_timestamp_seconds", int(started))
            metric(lines, "headnode_attribution_exporter_scrape_duration_seconds", time.time() - started)
            metric(lines, "headnode_host_logical_cpus", NCPU)
            metric(lines, "headnode_host_info", 1, hostname=socket.getfqdn(), ipv4=PRIMARY_IPV4, platform=PLATFORM)
            metric(lines, "iren_mkz_external_tcp_up", tcp_listener_up("192.0.2.1", 443), target="ufm-a", address="192.0.2.1", port="443", service="https")
            metric(lines, "iren_mkz_external_tcp_up", tcp_listener_up("192.0.2.1", 9001), target="ufm-a", address="192.0.2.1", port="9001", service="telemetry-csv")
            metric(lines, "iren_mkz_external_tcp_up", tcp_listener_up("192.0.2.7", 443), target="ufm-b", address="192.0.2.7", port="443", service="https")
            metric(lines, "iren_mkz_external_tcp_up", tcp_listener_up("192.0.2.7", 9001), target="ufm-b", address="192.0.2.7", port="9001", service="telemetry-csv")
            self.previous_time, self.previous_proc, self.previous_services = now, procs, services
            return "\n".join(lines) + "\n"


COLLECTOR = Collector()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/metrics", "/healthy", "/-/healthy"):
            self.send_error(404)
            return
        if self.path == "/metrics":
            body = COLLECTOR.collect().encode()
            content_type = "text/plain; version=0.0.4; charset=utf-8"
        else:
            body, content_type = b"ok\n", "text/plain; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
