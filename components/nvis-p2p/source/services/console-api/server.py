#!/usr/bin/env python3
from __future__ import annotations

import base64
import concurrent.futures
import csv
import glob
import http.client
import json
import os
import pathlib
import re
import signal
import ssl
import subprocess
import threading
import time
import urllib.request
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(os.environ.get("NVIS_P2P_ROOT", str(pathlib.Path(__file__).resolve().parents[2]))).expanduser().resolve()
CATALOG = ROOT / "catalog/images.json"
STATE = ROOT / "state/console-operations"
RUNNER = ROOT / "scripts/catalog-operation.sh"
PEER_APPLIER = ROOT / "scripts/apply-uncapped-node.sh"
PEER_TEMPLATE = ROOT / "configs/peer.template.yaml"
PEER_UNIT = ROOT / "deploy/systemd/nvis-p2p-peer.service"
SCHEDULER_CONFIG = ROOT / "configs/scheduler.yaml"
CONTROL_PLANE_COMPOSE = ROOT / "deploy/control-plane/compose.yaml"
SETTINGS_STATE = ROOT / "state/console-settings.json"
SETTINGS_OPERATIONS = ROOT / "state/console-settings-operations"
ELIGIBLE_NODES = pathlib.Path(os.environ.get("NVIS_P2P_ELIGIBLE_NODES", str(ROOT / "inventory/SU1-SU14-live-eligible-3951.nodes"))).expanduser().resolve()
MANAGER = os.environ.get("NVIS_P2P_MANAGER", "127.0.0.1:12004")
API_LISTEN_HOST = os.environ.get("NVIS_P2P_CONSOLE_API_LISTEN", "127.0.0.1")
API_LISTEN_PORT = int(os.environ.get("NVIS_P2P_CONSOLE_API_PORT", "14300"))
OBJECT_STORE_HEALTH_URL = os.environ.get("NVIS_P2P_OBJECT_STORE_HEALTH_URL", "https://192.0.2.10:19000/minio/health/live")
ALLOWED_ACTIONS = {"preflight", "deploy", "persist", "sync", "distribute", "verify", "repair"}
MUTATION_LOCK = threading.Lock()
ACTIVE: dict[str, subprocess.Popen[bytes]] = {}
SETTINGS_ACTIVE: dict[str, threading.Thread] = {}
STATE.mkdir(parents=True, exist_ok=True)
SETTINGS_OPERATIONS.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS = {
    "peer": {
        "download_bandwidth": "50GB",
        "upload_bandwidth": "50GB",
        "back_to_source_bandwidth": "50GB",
        "concurrent_pieces": 16,
    },
    "scheduler": {"redis_pool_size": 1024, "redis_pool_timeout": "10s"},
    "service_policy": {
        "mode": "uncapped",
        "cpu_quota_percent": None,
        "memory_max": None,
        "nice": None,
        "io_scheduling_class": None,
        "io_scheduling_priority": None,
    },
}

BANDWIDTH_RE = re.compile(r"^[1-9][0-9]*(?:KiB|MiB|GiB|TiB|KB|MB|GB|TB)$")
DURATION_RE = re.compile(r"^[1-9][0-9]*(?:ms|s|m)$")
MEMORY_RE = re.compile(r"^[1-9][0-9]*(?:K|M|G|T|KiB|MiB|GiB|TiB)$")


def atomic_json(path: pathlib.Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def deep_copy_default_settings() -> dict:
    return json.loads(json.dumps(DEFAULT_SETTINGS))


def normalize_settings(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("settings must be an object")
    peer = value.get("peer")
    scheduler = value.get("scheduler")
    policy = value.get("service_policy")
    if not all(isinstance(item, dict) for item in (peer, scheduler, policy)):
        raise ValueError("peer, scheduler, and service_policy objects are required")

    normalized = deep_copy_default_settings()
    for key in ("download_bandwidth", "upload_bandwidth", "back_to_source_bandwidth"):
        candidate = str(peer.get(key, "")).strip()
        if not BANDWIDTH_RE.fullmatch(candidate):
            raise ValueError(f"peer.{key} must be a positive bandwidth such as 50GB")
        normalized["peer"][key] = candidate
    try:
        pieces = int(peer.get("concurrent_pieces"))
    except (TypeError, ValueError):
        raise ValueError("peer.concurrent_pieces must be an integer") from None
    if not 1 <= pieces <= 256:
        raise ValueError("peer.concurrent_pieces must be between 1 and 256")
    normalized["peer"]["concurrent_pieces"] = pieces

    try:
        pool_size = int(scheduler.get("redis_pool_size"))
    except (TypeError, ValueError):
        raise ValueError("scheduler.redis_pool_size must be an integer") from None
    if not 16 <= pool_size <= 8192:
        raise ValueError("scheduler.redis_pool_size must be between 16 and 8192")
    pool_timeout = str(scheduler.get("redis_pool_timeout", "")).strip()
    if not DURATION_RE.fullmatch(pool_timeout):
        raise ValueError("scheduler.redis_pool_timeout must be a duration such as 10s")
    normalized["scheduler"].update({"redis_pool_size": pool_size, "redis_pool_timeout": pool_timeout})

    mode = str(policy.get("mode", "")).strip()
    if mode not in {"uncapped", "explicit"}:
        raise ValueError("service_policy.mode must be uncapped or explicit")
    normalized["service_policy"]["mode"] = mode
    if mode == "explicit":
        try:
            cpu = int(policy.get("cpu_quota_percent"))
            nice = int(policy.get("nice"))
            io_priority = int(policy.get("io_scheduling_priority"))
        except (TypeError, ValueError):
            raise ValueError("explicit CPU quota, nice, and I/O priority must be integers") from None
        memory = str(policy.get("memory_max", "")).strip()
        io_class = str(policy.get("io_scheduling_class", "")).strip()
        if not 1 <= cpu <= 6400:
            raise ValueError("service_policy.cpu_quota_percent must be between 1 and 6400")
        if not MEMORY_RE.fullmatch(memory):
            raise ValueError("service_policy.memory_max must be a size such as 8G")
        if not -20 <= nice <= 19:
            raise ValueError("service_policy.nice must be between -20 and 19")
        if io_class not in {"best-effort", "idle", "realtime"}:
            raise ValueError("service_policy.io_scheduling_class is invalid")
        if not 0 <= io_priority <= 7:
            raise ValueError("service_policy.io_scheduling_priority must be between 0 and 7")
        normalized["service_policy"].update({
            "cpu_quota_percent": cpu,
            "memory_max": memory,
            "nice": nice,
            "io_scheduling_class": io_class,
            "io_scheduling_priority": io_priority,
        })
    return normalized


def desired_settings() -> dict:
    if SETTINGS_STATE.exists():
        try:
            return normalize_settings(json.loads(SETTINGS_STATE.read_text())["settings"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            pass
    return deep_copy_default_settings()


def replace_required(text: str, pattern: str, replacement: str, label: str) -> str:
    value, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"unable to locate {label} in runtime template")
    return value


def render_settings(settings: dict) -> dict[pathlib.Path, str]:
    peer = PEER_TEMPLATE.read_text()
    mappings = (
        (r"^([ \t]*bandwidthLimit:)[ \t]*\S+[ \t]*$", rf"\g<1> {settings['peer']['download_bandwidth']}", "peer download bandwidth"),
        (r"^([ \t]*backToSourceBandwidthLimit:)[ \t]*\S+[ \t]*$", rf"\g<1> {settings['peer']['back_to_source_bandwidth']}", "back-to-source bandwidth"),
        (r"^([ \t]*concurrentPieceCount:)[ \t]*\S+[ \t]*$", rf"\g<1> {settings['peer']['concurrent_pieces']}", "concurrent pieces"),
    )
    for pattern, replacement, label in mappings:
        peer = replace_required(peer, pattern, replacement, label)
    upload_start = peer.index("\nupload:")
    upload_end = peer.index("\nscheduler:", upload_start)
    upload = replace_required(
        peer[upload_start:upload_end],
        r"^([ \t]*bandwidthLimit:)[ \t]*\S+[ \t]*$",
        rf"\g<1> {settings['peer']['upload_bandwidth']}",
        "peer upload bandwidth",
    )
    peer = peer[:upload_start] + upload + peer[upload_end:]

    scheduler = SCHEDULER_CONFIG.read_text()
    scheduler = replace_required(scheduler, r"^([ \t]*poolSize:)[ \t]*\S+[ \t]*$", rf"\g<1> {settings['scheduler']['redis_pool_size']}", "Redis pool size")
    scheduler = replace_required(scheduler, r"^([ \t]*poolTimeout:)[ \t]*\S+[ \t]*$", rf"\g<1> {settings['scheduler']['redis_pool_timeout']}", "Redis pool timeout")

    unit = PEER_UNIT.read_text()
    unit = re.sub(r"^(?:CPUQuota|MemoryMax|Nice|IOSchedulingClass|IOSchedulingPriority)=.*\n", "", unit, flags=re.MULTILINE)
    marker = "LimitNOFILE=1048576\n"
    if marker not in unit:
        raise ValueError("unable to locate peer service policy insertion point")
    if settings["service_policy"]["mode"] == "explicit":
        policy = settings["service_policy"]
        directives = (
            f"CPUQuota={policy['cpu_quota_percent']}%\n"
            f"MemoryMax={policy['memory_max']}\n"
            f"Nice={policy['nice']}\n"
            f"IOSchedulingClass={policy['io_scheduling_class']}\n"
            f"IOSchedulingPriority={policy['io_scheduling_priority']}\n"
        )
        unit = unit.replace(marker, marker + directives, 1)
    return {PEER_TEMPLATE: peer, SCHEDULER_CONFIG: scheduler, PEER_UNIT: unit}


def atomic_apply_files(rendered: dict[pathlib.Path, str], settings: dict) -> None:
    originals = {path: path.read_bytes() for path in rendered}
    settings_original = SETTINGS_STATE.read_bytes() if SETTINGS_STATE.exists() else None
    temporary: dict[pathlib.Path, pathlib.Path] = {}
    try:
        for path, text in rendered.items():
            candidate = path.with_name(f".{path.name}.console-{uuid.uuid4().hex}.tmp")
            with candidate.open("w") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            candidate.chmod(path.stat().st_mode & 0o777)
            temporary[path] = candidate
        for path, candidate in temporary.items():
            candidate.replace(path)
        atomic_json(SETTINGS_STATE, {
            "version": 1,
            "settings": settings,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    except Exception:
        for path, content in originals.items():
            candidate = path.with_name(f".{path.name}.rollback-{uuid.uuid4().hex}.tmp")
            candidate.write_bytes(content)
            candidate.replace(path)
        if settings_original is not None:
            candidate = SETTINGS_STATE.with_name(f".{SETTINGS_STATE.name}.rollback-{uuid.uuid4().hex}.tmp")
            candidate.write_bytes(settings_original)
            candidate.replace(SETTINGS_STATE)
        elif SETTINGS_STATE.exists():
            SETTINGS_STATE.unlink()
        raise
    finally:
        for candidate in temporary.values():
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass


def settings_diff(settings: dict) -> tuple[dict[pathlib.Path, str], list[str]]:
    rendered = render_settings(settings)
    changed = [str(path.relative_to(ROOT)) for path, value in rendered.items() if path.read_text() != value]
    return rendered, changed


def settings_operation_payload(path: pathlib.Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def settings_operations() -> list[dict]:
    values = []
    for path in sorted(SETTINGS_OPERATIONS.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:10]:
        value = settings_operation_payload(path)
        if value:
            values.append(value)
    return values


def settings_status_payload() -> dict:
    desired = desired_settings()
    _, drift = settings_diff(desired)
    operations = settings_operations()
    return {
        "defaults": deep_copy_default_settings(),
        "desired": desired,
        "drift": drift,
        "operations": operations,
        "active": next((item for item in operations if item.get("state") == "running"), None),
        "scope": {"eligible_nodes": len(ELIGIBLE_NODES.read_text().splitlines()) if ELIGIBLE_NODES.exists() else 0},
    }


def update_settings_operation(operation_id: str, **changes) -> dict:
    path = SETTINGS_OPERATIONS / f"{operation_id}.json"
    value = settings_operation_payload(path) or {"id": operation_id}
    value.update(changes)
    atomic_json(path, value)
    return value


def append_operation_log(operation_id: str, message: str) -> None:
    with (SETTINGS_OPERATIONS / f"{operation_id}.log").open("a") as stream:
        stream.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message.rstrip()}\n")


def reconcile_settings(operation_id: str, settings: dict, peer_changed: bool, scheduler_changed: bool, force: bool) -> None:
    failures: list[dict] = []
    try:
        if scheduler_changed or force:
            append_operation_log(operation_id, "scheduler reconcile begin")
            command = ["docker", "compose", "-f", str(CONTROL_PLANE_COMPOSE), "up", "-d", "--no-deps"]
            if scheduler_changed:
                command.append("--force-recreate")
            command.append("scheduler")
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
            append_operation_log(operation_id, result.stdout)
            if result.returncode:
                raise RuntimeError(f"scheduler reconcile failed with exit {result.returncode}")

        nodes = [node for node in ELIGIBLE_NODES.read_text().splitlines() if node] if peer_changed or force else []
        update_settings_operation(operation_id, total=len(nodes), completed=0, succeeded=0, failed=0, phase="peer_reconcile" if nodes else "finalizing")
        progress_lock = threading.Lock()
        progress = {"completed": 0, "succeeded": 0, "failed": 0}

        def apply_node(node: str) -> None:
            result = subprocess.run([str(PEER_APPLIER), node], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
            detail = result.stdout.strip()[-2000:]
            if result.returncode == 0 and settings["service_policy"]["mode"] == "explicit":
                policy = settings["service_policy"]
                limit = subprocess.run([
                    "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", node,
                    "sudo", "-n", "systemctl", "set-property", "--runtime", "nvis-p2p-peer.service",
                    f"CPUQuota={policy['cpu_quota_percent']}%", f"MemoryMax={policy['memory_max']}",
                ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
                detail += "\n" + limit.stdout.strip()
                if limit.returncode:
                    result = subprocess.CompletedProcess(result.args, limit.returncode, detail)
            with progress_lock:
                progress["completed"] += 1
                outcome = "succeeded" if result.returncode == 0 else "failed"
                progress[outcome] += 1
                if result.returncode:
                    failures.append({"node": node, "return_code": result.returncode, "detail": detail})
                append_operation_log(operation_id, f"node={node} state={outcome} {detail}")
                update_settings_operation(operation_id, **progress, errors=failures[-50:])

        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
            list(executor.map(apply_node, nodes))
        state = "succeeded" if not failures else "completed_with_errors"
        update_settings_operation(operation_id, state=state, phase="complete", finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), errors=failures[-50:])
    except Exception as error:
        append_operation_log(operation_id, f"fatal={error}")
        update_settings_operation(operation_id, state="failed", phase="failed", message=str(error), finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), errors=failures[-50:])
    finally:
        SETTINGS_ACTIVE.pop(operation_id, None)
        MUTATION_LOCK.release()


def start_settings_operation(settings: dict, changed: list[str], force: bool) -> dict:
    operation_id = str(uuid.uuid4())
    metadata = {
        "id": operation_id,
        "kind": "settings_reconcile" if force else "settings_apply",
        "state": "running",
        "phase": "queued",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "changed": changed,
        "total": 0,
        "completed": 0,
        "succeeded": 0,
        "failed": 0,
        "errors": [],
        "log": f"/nvis/api/settings/operations/{operation_id}/log",
    }
    atomic_json(SETTINGS_OPERATIONS / f"{operation_id}.json", metadata)
    peer_changed = force or any(path in changed for path in (str(PEER_TEMPLATE.relative_to(ROOT)), str(PEER_UNIT.relative_to(ROOT))))
    scheduler_changed = str(SCHEDULER_CONFIG.relative_to(ROOT)) in changed
    thread = threading.Thread(target=reconcile_settings, args=(operation_id, settings, peer_changed, scheduler_changed, force), daemon=True)
    SETTINGS_ACTIVE[operation_id] = thread
    thread.start()
    return metadata


def decode_user_id(token: str) -> int:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    value = json.loads(base64.urlsafe_b64decode(payload.encode()))
    return int(value["id"])


def is_root(cookie_header: str) -> bool:
    try:
        cookie = SimpleCookie(cookie_header)
        token = cookie["jwt"].value
        user_id = decode_user_id(token)
        connection = http.client.HTTPConnection(MANAGER, timeout=3)
        connection.request("GET", f"/api/v1/users/{user_id}/roles", headers={"Cookie": cookie_header})
        response = connection.getresponse()
        payload = json.loads(response.read()) if response.status == 200 else []
        connection.close()
        return "root" in payload
    except Exception:
        return False


def su_for_node(node: str) -> int | None:
    match = re.match(r"ink50-(dh0[12])-([a-z])", node)
    if not match:
        return None
    host, letter = match.groups()
    number = ord(letter) - 96
    return number if host == "dh02" else number + 11


def latest_preflight() -> pathlib.Path | None:
    matches = [pathlib.Path(p) for p in glob.glob(str(ROOT / "state/catalog-preflight-*.tsv"))]
    return max(matches, key=lambda p: p.stat().st_mtime) if matches else None


def coverage_snapshots() -> list[pathlib.Path]:
    return sorted(
        (pathlib.Path(p) for p in glob.glob(str(ROOT / "state/catalog-verify-*.tsv"))),
        key=lambda path: path.stat().st_mtime,
    )


def latest_sync_run() -> pathlib.Path | None:
    candidates = []
    for path in ROOT.joinpath("state").glob("catalog-sync-*"):
        nodes = path / "nodes"
        tracking = path / "tracking.tsv"
        if path.is_dir() and nodes.exists() and tracking.exists():
            # nodes is written once when a wave starts. Mutable tracking files
            # from an older concurrent wave must not make that wave "latest".
            candidates.append((nodes.stat().st_mtime, path))
    return max(candidates, default=(0, None), key=lambda item: item[0])[1]


def sync_run_payload() -> dict | None:
    path = latest_sync_run()
    if not path:
        return None

    def rows(filename: str) -> list[dict]:
        source = path / filename
        if not source.exists():
            return []
        try:
            with source.open() as stream:
                return list(csv.DictReader(stream, delimiter="\t"))
        except (OSError, csv.Error):
            return []

    nodes = {node for node in (path / "nodes").read_text().splitlines() if node}
    complete_rows = rows("complete.tsv")
    deferred_rows = rows("deferred.tsv")
    tracking_rows = rows("tracking.tsv")
    complete = {record.get("node") for record in complete_rows if record.get("node") in nodes}
    deferred = {record.get("node"): record.get("reason", "deferred") for record in deferred_rows if record.get("node") in nodes}
    tracking = {record.get("node"): record for record in tracking_rows if record.get("node") in nodes}
    pending = nodes - complete - set(deferred)
    relevant = [item for item in (path / "tracking.tsv", path / "complete.tsv", path / "deferred.tsv", path / "summary.tsv") if item.exists()]
    updated = max((item.stat().st_mtime for item in relevant), default=path.stat().st_mtime)
    finished = (path / "summary.tsv").exists() or not pending
    return {
        "id": path.name,
        "state": ("complete_with_deferrals" if deferred else "complete") if finished else "running",
        "total": len(nodes),
        "complete": len(complete),
        "pending": len(pending),
        "deferred": len(deferred),
        "percent": round(100 * len(complete) / len(nodes), 1) if nodes else 0,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(updated)),
        "nodes": {
            node: ({"state": "complete", "detail": "NVIS_P2P_SYNC_COMPLETE failed=0"} if node in complete else
                   {"state": "deferred", "detail": deferred[node]} if node in deferred else
                   {"state": "pending", "detail": tracking.get(node, {}).get("last_detail", "start queued")})
            for node in nodes
        },
    }


def coverage_payload(sync: dict | None = None) -> dict:
    catalog = json.loads(CATALOG.read_text())
    required = [image["filename"] for image in catalog["images"]]
    eligible_path = ROOT / "inventory/SU1-SU14-eligible-3953.nodes"
    eligible = set(eligible_path.read_text().splitlines()) if eligible_path.exists() else set()
    nodes: dict[str, dict] = {}
    for su in range(1, 15):
        roster = ROOT / f"inventory/SU{su}-288.nodes"
        if not roster.exists():
            continue
        for node in roster.read_text().splitlines():
            if node:
                nodes[node] = {"node": node, "su": su, "state": "unavailable" if node in eligible else "not-eligible", "present": 0, "verified": 0, "unverified": 0, "missing": len(required), "bad_size": 0, "active": 0, "images": {}, "observed_at": None}

    snapshots = coverage_snapshots()
    for snapshot in snapshots:
        with snapshot.open() as stream:
            next(stream, None)
            for line in stream:
                columns = line.rstrip("\n").split("\t")
                if not columns or columns[0] not in nodes:
                    continue
                node = columns[0]
                if len(columns) == 2 and columns[1] == "unreachable":
                    nodes[node]["state"] = "unreachable"
                    nodes[node]["observed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(snapshot.stat().st_mtime))
                    continue
                fields = {}
                for column in columns[1:]:
                    if "=" in column:
                        key, value = column.split("=", 1)
                        fields[key] = value
                try:
                    verified = int(fields.get("ready", 0))
                    unverified = int(fields.get("unverified", 0))
                    missing = int(fields.get("missing", len(required)))
                    bad_size = int(fields.get("bad_size", 0))
                    active = int(fields.get("active", 0))
                except ValueError:
                    continue
                image_states = {}
                for value in fields.get("images", "").split(","):
                    if ":" in value:
                        filename, state = value.rsplit(":", 1)
                        image_states[filename] = state
                nodes[node].update({
                    "state": "syncing" if active else ("complete" if verified == len(required) and not unverified and not missing and not bad_size else "incomplete"),
                    "present": verified + unverified,
                    "verified": verified,
                    "unverified": unverified,
                    "missing": missing,
                    "bad_size": bad_size,
                    "active": active,
                    "images": image_states,
                    "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(snapshot.stat().st_mtime)),
                })

    # Overlay the controller's local run files so the UI follows the current
    # wave without opening any new compute-node connections.
    if sync:
        for node, value in sync["nodes"].items():
            if node not in nodes:
                continue
            nodes[node]["sync_state"] = value["state"]
            nodes[node]["sync_detail"] = value["detail"]
            if value["state"] == "complete":
                nodes[node].update({"state": "complete", "present": len(required), "verified": len(required), "unverified": 0, "missing": 0, "bad_size": 0, "active": 0})
            elif value["state"] == "pending":
                nodes[node].update({"state": "syncing", "active": 1})
            else:
                nodes[node]["state"] = "unavailable"

    by_su = []
    for su in range(1, 15):
        group = [record for record in nodes.values() if record["su"] == su]
        distribution = {str(count): 0 for count in range(len(required) + 1)}
        for record in group:
            distribution[str(record["present"])] += 1
        by_su.append({
            "su": su,
            "distribution": distribution,
            "complete": sum(record["state"] == "complete" for record in group),
            "syncing": sum(record["state"] == "syncing" for record in group),
            "incomplete": sum(record["state"] == "incomplete" for record in group),
            "unavailable": sum(record["state"] in {"not-eligible", "unreachable", "unavailable"} for record in group),
        })
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(snapshots[-1].stat().st_mtime)) if snapshots else None,
        "required_count": len(required),
        "required_images": required,
        "by_su": by_su,
        "nodes": sorted(nodes.values(), key=lambda record: (record["su"], record["node"])),
    }


def fleet_summary() -> list[dict]:
    catalog_size = len(json.loads(CATALOG.read_text())["images"])
    rows = {su: {"su": su, "total": 288, "reachable": 0, "eligible": 0, "peers": 0, "ready": 0} for su in range(1, 15)}
    snapshots = sorted(
        (pathlib.Path(p) for p in glob.glob(str(ROOT / "state/catalog-preflight-*.tsv"))),
        key=lambda path: path.stat().st_mtime,
    )
    if not snapshots:
        return list(rows.values())
    newest_by_node: dict[str, dict] = {}
    for path in snapshots:
        with path.open() as stream:
            for record in csv.DictReader(stream, delimiter="\t"):
                if record.get("node"):
                    newest_by_node[record["node"]] = record
    for record in newest_by_node.values():
        su = su_for_node(record["node"])
        if not su:
            continue
        item = rows[su]
        if record["ssh"] != "reachable":
            continue
        item["reachable"] += 1
        eligible = all((record["page_size"] == "65536", record["arch"] == "aarch64", record["uid"] == "1024", record["gid"] == "1003", record["sudo_n"] == "yes", record["opt_writable"] == "yes"))
        if eligible:
            item["eligible"] += 1
        if record["peer"] == "socket":
            item["peers"] += 1
        try:
            if int(record["active_dfget:ready_images:missing_bytes"].split(":")[1]) == catalog_size:
                item["ready"] += 1
        except Exception:
            pass
    return list(rows.values())


def object_store_healthy() -> bool:
    try:
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(OBJECT_STORE_HEALTH_URL, timeout=2, context=context) as response:
            return response.status == 200
    except Exception:
        return False


def status_payload() -> dict:
    catalog = json.loads(CATALOG.read_text())
    for image in catalog["images"]:
        path = pathlib.Path(catalog["canonical_directory"]) / image["filename"]
        image["canonical_present"] = path.is_file() and path.stat().st_size == image["bytes"]
        receipt = ROOT / "state/persistence" / f"{image['filename']}.tsv"
        image["persistent_import"] = receipt.read_text().strip().split("\t") if receipt.exists() else None
    operations = []
    for path in sorted(STATE.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        try:
            operations.append(json.loads(path.read_text()))
        except Exception:
            pass
    preflight = latest_preflight()
    sync = sync_run_payload()
    coverage = coverage_payload(sync)
    coverage_by_su = {item["su"]: item for item in coverage["by_su"]}
    fleet = fleet_summary()
    for item in fleet:
        current = coverage_by_su[item["su"]]
        item.update({"ready": current["complete"], "syncing": current["syncing"], "incomplete": current["incomplete"], "unavailable": current["unavailable"], "distribution": current["distribution"]})
    hashes: dict[str, list[str]] = {}
    for image in catalog["images"]:
        hashes.setdefault(image["sha256"], []).append(image["filename"])
    return {
        "catalog": catalog,
        "object_store_healthy": object_store_healthy(),
        "fleet": fleet,
        "coverage": coverage,
        "sync": {key: value for key, value in sync.items() if key != "nodes"} if sync else None,
        "catalog_exact_duplicates": [files for files in hashes.values() if len(files) > 1],
        "preflight_generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(preflight.stat().st_mtime)) if preflight else None,
        "operations": operations,
    }


def monitor(operation_id: str, process: subprocess.Popen[bytes], log_stream) -> None:
    return_code = process.wait()
    log_stream.close()
    path = STATE / f"{operation_id}.json"
    try:
        value = json.loads(path.read_text())
    except Exception:
        value = {"id": operation_id}
    value.update({"state": "succeeded" if return_code == 0 else "failed", "return_code": return_code, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    atomic_json(path, value)
    ACTIVE.pop(operation_id, None)
    MUTATION_LOCK.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "NVIS-P2P-Console-API/1"

    def send_json(self, status: int, value: dict) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self) -> bool:
        return is_root(self.headers.get("Cookie", ""))

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})
            return
        if not self.authorized():
            self.send_json(403, {"message": "root role required"})
            return
        if self.path == "/status":
            self.send_json(200, status_payload())
            return
        if self.path == "/settings":
            try:
                self.send_json(200, settings_status_payload())
            except Exception as error:
                self.send_json(500, {"message": str(error)})
            return
        if self.path.startswith("/settings/operations/") and self.path.endswith("/log"):
            operation_id = self.path.split("/")[3]
            if not re.fullmatch(r"[0-9a-f-]{36}", operation_id):
                self.send_json(400, {"message": "invalid operation id"})
                return
            path = SETTINGS_OPERATIONS / f"{operation_id}.log"
            body = path.read_bytes()[-200000:] if path.exists() else b""
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/operations/") and self.path.endswith("/log"):
            operation_id = self.path.split("/")[2]
            if not re.fullmatch(r"[0-9a-f-]{36}", operation_id):
                self.send_json(400, {"message": "invalid operation id"})
                return
            path = STATE / f"{operation_id}.log"
            body = path.read_bytes()[-200000:] if path.exists() else b""
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_json(404, {"message": "not found"})

    def do_POST(self) -> None:
        if not self.authorized():
            self.send_json(403, {"message": "root role required"})
            return
        if self.path in {"/settings/validate", "/settings/apply", "/settings/reconcile"}:
            self.handle_settings_post()
            return
        if self.path != "/operations":
            self.send_json(404, {"message": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 65536:
                raise ValueError("invalid request size")
            request = json.loads(self.rfile.read(length))
            action = str(request["action"])
            sus = sorted({int(v) for v in request["sus"]})
            images = list(dict.fromkeys(str(v) for v in request.get("images", [])))
            catalog_names = {x["filename"] for x in json.loads(CATALOG.read_text())["images"]}
            if action not in ALLOWED_ACTIONS or not sus or any(v < 1 or v > 14 for v in sus) or any(v not in catalog_names for v in images):
                raise ValueError("invalid operation selection")
            if action in {"distribute", "repair"} and len(images) != 1:
                raise ValueError("distribution and repair require exactly one image")
        except Exception as error:
            self.send_json(400, {"message": str(error)})
            return
        if not MUTATION_LOCK.acquire(blocking=False):
            self.send_json(409, {"message": "another fleet operation is active"})
            return
        operation_id = str(uuid.uuid4())
        log_path = STATE / f"{operation_id}.log"
        metadata = {
            "id": operation_id,
            "action": action,
            "sus": sus,
            "images": images,
            "state": "running",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "log": f"/nvis/api/operations/{operation_id}/log",
        }
        atomic_json(STATE / f"{operation_id}.json", metadata)
        log_stream = log_path.open("ab", buffering=0)
        try:
            process = subprocess.Popen([str(RUNNER), action, ",".join(map(str, sus)), ",".join(images)], stdout=log_stream, stderr=subprocess.STDOUT, start_new_session=True)
        except Exception as error:
            log_stream.close()
            MUTATION_LOCK.release()
            metadata.update({"state": "failed", "message": str(error)})
            atomic_json(STATE / f"{operation_id}.json", metadata)
            self.send_json(500, metadata)
            return
        ACTIVE[operation_id] = process
        threading.Thread(target=monitor, args=(operation_id, process, log_stream), daemon=True).start()
        metadata["pid"] = process.pid
        atomic_json(STATE / f"{operation_id}.json", metadata)
        self.send_json(202, metadata)

    def handle_settings_post(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 65536:
                raise ValueError("invalid request size")
            request = json.loads(self.rfile.read(length))
            settings = normalize_settings(request.get("settings", desired_settings()))
            rendered, changed = settings_diff(settings)
            plan = {
                "valid": True,
                "settings": settings,
                "changed": changed,
                "scheduler_reconcile": str(SCHEDULER_CONFIG.relative_to(ROOT)) in changed,
                "peer_reconcile": any(path in changed for path in (str(PEER_TEMPLATE.relative_to(ROOT)), str(PEER_UNIT.relative_to(ROOT)))),
                "eligible_nodes": len(ELIGIBLE_NODES.read_text().splitlines()) if ELIGIBLE_NODES.exists() else 0,
                "preserves": ["peer caches", "materialized artifacts", "catalog receipts", "unrelated services"],
            }
        except Exception as error:
            self.send_json(400, {"valid": False, "message": str(error)})
            return
        if self.path == "/settings/validate":
            self.send_json(200, plan)
            return
        if not MUTATION_LOCK.acquire(blocking=False):
            self.send_json(409, {"message": "another fleet operation is active"})
            return
        try:
            force = self.path == "/settings/reconcile"
            if not force:
                atomic_apply_files(rendered, settings)
            metadata = start_settings_operation(settings, changed, force)
        except Exception as error:
            MUTATION_LOCK.release()
            self.send_json(500, {"message": str(error)})
            return
        self.send_json(202, {**metadata, "plan": plan})

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer((API_LISTEN_HOST, API_LISTEN_PORT), Handler)
    server.serve_forever()
