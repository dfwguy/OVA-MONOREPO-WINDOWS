"""Native Windows scheduling adapter for one upstream Auto Action node/test.

The original Linux launcher owns validation and verdict semantics. This adapter
owns only the Windows cadence, exclusive invocation and private receipts.
"""
import argparse
import hashlib
import json
import re
import shlex
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
FIELDS = {"schema_version", "ssh_alias", "node", "test", "remote_root",
          "fanout", "state_directory", "mode", "execute_authorized",
          "launcher_sha256", "timeout_seconds"}


def load_config(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or set(value) != FIELDS or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Configuration must match site.example.json exactly")
    for key in ("ssh_alias", "node", "test"):
        if not isinstance(value[key], str) or not IDENTIFIER.fullmatch(value[key]):
            raise ValueError(f"{key} must be one explicit identifier, never a host list")
    root = value["remote_root"]
    if not isinstance(root, str) or not PurePosixPath(root).is_absolute() or ".." in PurePosixPath(root).parts or re.search(r"[\r\n\x00]", root):
        raise ValueError("remote_root must be an absolute Linux path without traversal")
    if value["fanout"] not in ("clush", "pdsh") or value["mode"] not in ("preview", "execute"):
        raise ValueError("Choose clush/pdsh and preview/execute explicitly")
    if type(value["execute_authorized"]) is not bool:
        raise ValueError("execute_authorized must be a boolean")
    if value["mode"] == "execute" and not value["execute_authorized"]:
        raise ValueError("Execution requires explicit site authorization")
    if not re.fullmatch(r"[a-f0-9]{64}", value["launcher_sha256"]):
        raise ValueError("Pin the reviewed remote launcher SHA256")
    if type(value["timeout_seconds"]) is not int or not 10 <= value["timeout_seconds"] <= 600:
        raise ValueError("timeout_seconds must be 10..600")
    if not isinstance(value["state_directory"], str) or not Path(value["state_directory"]).is_absolute():
        raise ValueError("state_directory must be a private absolute path")
    if Path(value["state_directory"]).resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("Runtime state must be outside the source repository")
    return value


def command(config, receipt_nonce="plan"):
    launcher = str(PurePosixPath(config["remote_root"]) / "actions/launch_job.sh")
    invocation = ["bash", launcher, "--test", config["test"]]
    if config["mode"] == "preview":
        invocation.append("--explain")
    # Source hash and launcher run are checked on the same explicitly scoped node.
    node_command = ("set -eu; printf '%s  %s\\n' " +
                    shlex.quote(config["launcher_sha256"]) + " " + shlex.quote(launcher) +
                    " | sha256sum -c - >/dev/null; " + shlex.join(invocation) +
                    "; printf '%s\\n' " + shlex.quote("OVA_REMOTE_DONE:" + receipt_nonce))
    node_invocation = shlex.join(["bash", "-lc", node_command])
    fanout_path = str(PurePosixPath(config["remote_root"]) / "fanout.sh")
    head_command = ("set -eu; source " + shlex.quote(fanout_path) +
                    "; FANOUT_TOOL=" + shlex.quote(config["fanout"]) + "; " +
                    shlex.join(["fanout", config["node"], node_invocation]))
    remote = shlex.join(["bash", "-lc", head_command])
    return ["ssh.exe" if sys.platform == "win32" else "ssh", "-T", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=15", config["ssh_alias"], remote]


def cycle(config, runner=subprocess.run):
    state = Path(config["state_directory"])
    state.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(state / "controller.sqlite3", timeout=0)
    run_id = uuid.uuid4().hex
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,status TEXT,started REAL,finished REAL,exit_code INTEGER,scope TEXT)")
        if "scope" not in {row[1] for row in db.execute("PRAGMA table_info(runs)")}:
            db.execute("ALTER TABLE runs ADD COLUMN scope TEXT")
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        unresolved = db.execute("SELECT id FROM runs WHERE status IN ('started','uncertain') LIMIT 1").fetchone()
        if unresolved:
            raise RuntimeError("An unresolved invocation requires scheduler/result reconciliation; no automatic replay")
        scope = hashlib.sha256(json.dumps({key: config[key] for key in ("ssh_alias", "node", "test", "remote_root", "mode", "launcher_sha256")}, sort_keys=True).encode()).hexdigest()
        if config["mode"] == "execute" and db.execute("SELECT id FROM runs WHERE status='completed' AND scope=? LIMIT 1", (scope,)).fetchone():
            raise RuntimeError("This execution scope was already invoked; review scheduler/results before authorizing a new campaign")
        db.execute("INSERT INTO runs VALUES(?,?,?,NULL,NULL,?)", (run_id, "started", time.time(), scope))
        db.commit()
        output = state / run_id
        output.mkdir()
        try:
            result = runner(command(config, run_id), capture_output=True, timeout=config["timeout_seconds"], check=False)
            (output / "stdout.txt").write_bytes(result.stdout or b"")
            (output / "stderr.txt").write_bytes(result.stderr or b"")
            confirmed = ("OVA_REMOTE_DONE:" + run_id).encode() in (result.stdout or b"")
            status = "completed" if result.returncode == 0 and confirmed else "uncertain"
            code = result.returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            # A disconnected SSH command may already have submitted work.
            status, code = "uncertain", None
            (output / "transport-error.txt").write_text(type(error).__name__ + "\n")
        db.execute("UPDATE runs SET status=?,finished=?,exit_code=? WHERE id=?", (status, time.time(), code, run_id))
        db.commit()
        receipt = {"schema_version": 1, "id": run_id, "status": status,
                   "mode": config["mode"], "transport_exit_code": code,
                   "workload_acceptance": "not established by transport exit",
                   "logs_directory": str(output)}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return receipt
    finally:
        db.close()


def render_task(config_path, python, output):
    config = load_config(config_path)
    if not Path(python).is_absolute():
        raise ValueError("Use an absolute native Python executable")
    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", ns)
    def add(parent, tag, text=None):
        child = ET.SubElement(parent, "{" + ns + "}" + tag)
        child.text = text
        return child
    root = ET.Element("{" + ns + "}Task", version="1.4")
    info = add(root, "RegistrationInfo")
    add(info, "Description", "OVA one-node Auto Action adapter; site-owned identity and scope; preview by default")
    triggers = add(root, "Triggers")
    trigger = add(triggers, "TimeTrigger")
    repetition = add(trigger, "Repetition")
    add(repetition, "Interval", "PT2M")
    add(repetition, "StopAtDurationEnd", "false")
    add(trigger, "StartBoundary", "2026-01-01T00:00:00")
    add(trigger, "Enabled", "true")
    settings = add(root, "Settings")
    add(settings, "MultipleInstancesPolicy", "IgnoreNew")
    add(settings, "ExecutionTimeLimit", "PT" + str(config["timeout_seconds"] + 30) + "S")
    add(settings, "Enabled", "false")
    actions = add(root, "Actions")
    execution = add(actions, "Exec")
    add(execution, "Command", str(Path(python)))
    add(execution, "Arguments", subprocess.list2cmdline([str(Path(__file__).resolve()), "cycle", "--config", str(Path(config_path).resolve())]))
    with Path(output).open("xb") as stream:
        stream.write(ET.tostring(root, encoding="utf-16", xml_declaration=True))
    return {"status": "DISABLED_TASK_RENDERED", "path": str(output), "registered": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "cycle", "render-task"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--python")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.action == "plan":
            result = {"mode": config["mode"], "node_count": 1, "command": command(config), "executed": False}
        elif args.action == "render-task":
            if not args.python or not args.output:
                raise ValueError("render-task requires --python and --output")
            result = render_task(args.config, args.python, args.output)
        else:
            result = cycle(config)
        print(json.dumps(result, indent=2))
        return 1 if result.get("status") == "uncertain" else 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
