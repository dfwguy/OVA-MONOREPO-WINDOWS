#!/usr/bin/env python3
"""Validate deployment inputs and integrity of reviewed offline payloads.

No network access, infrastructure mutation, credential reads or job submissions.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath


def positive(value, label):
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")


def choice(value, values, label):
    if value not in values:
        raise ValueError(f"{label} must be one of {', '.join(values)}")


def validate_config(data):
    """Structural validation, not platform readiness or recipe compatibility."""
    if not isinstance(data, dict):
        raise ValueError("deployment configuration must be a mapping")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    raw = json.dumps(data)
    if re.search(r"<[A-Z_a-z][^>]*>", raw):
        raise ValueError("replace every template placeholder before validation")
    if re.search(r"(?:hf_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{15,})", raw):
        raise ValueError("credential-like value in deployment configuration")
    for section in ("upstream", "hardware", "scheduler", "storage", "credentials"):
        if not isinstance(data.get(section), dict):
            raise ValueError(f"missing mapping: {section}")
    allowed = {
        "root": {"schema_version", "cluster_alias", "network_mode", "upstream", "hardware", "scheduler", "storage", "credentials", "workloads"},
        "upstream": {"repository", "commit", "release"},
        "hardware": {"architecture", "gpu_type", "gpus_per_node", "nodes", "transport", "expected_hcas_per_node", "socket_interface", "transport_environment"},
        "scheduler": {"type", "account", "partition", "qos", "operator_user"},
        "storage": {"layout", "source_root", "install_root", "image_root", "hf_cache", "evidence_root"},
        "credentials": {"hf_token_file", "ngc_credentials_file"},
    }
    for section, fields in allowed.items():
        mapping = data if section == "root" else data[section]
        if set(mapping) != fields:
            raise ValueError(f"{section} fields differ from the template; credential references only")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", data.get("cluster_alias", "")):
        raise ValueError("cluster_alias must be a short, non-sensitive alias")
    choice(data.get("network_mode"), ("connected", "airgap"), "network_mode")
    if not re.fullmatch(r"[a-f0-9]{40}", data["upstream"].get("commit", "")):
        raise ValueError("upstream.commit must be an immutable full Git commit")
    if data["upstream"].get("repository") != "https://github.com/NVIDIA/exemplar-performance.git":
        raise ValueError("use the canonical upstream repository; document mirrors separately")
    if not data["upstream"].get("release"):
        raise ValueError("upstream.release is required")
    h = data["hardware"]
    choice(h.get("architecture"), ("x86_64", "aarch64"), "architecture")
    choice(h.get("transport"), ("infiniband", "roce", "efa", "socket"), "transport")
    positive(h.get("gpus_per_node"), "gpus_per_node")
    count = h.get("expected_hcas_per_node")
    if type(count) is not int or count < 0:
        raise ValueError("expected_hcas_per_node must be a nonnegative integer")
    if h["transport"] in ("infiniband", "roce") and count == 0:
        raise ValueError("RDMA transport requires an explicit nonzero HCA count")
    nodes = h.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("nodes must contain unique explicit hostnames")
    if any(not isinstance(n, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", n) for n in nodes):
        raise ValueError("invalid hostname in nodes")
    if len(nodes) != len(set(nodes)):
        raise ValueError("nodes must contain unique explicit hostnames")
    if not h.get("gpu_type") or not h.get("socket_interface"):
        raise ValueError("gpu_type and socket_interface are required")
    env = h.get("transport_environment")
    if not isinstance(env, dict):
        raise ValueError("transport_environment must be a mapping")
    for key, value in env.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not isinstance(value, str):
            raise ValueError("transport environment needs uppercase keys and string values")
        if re.search(r"TOKEN|PASSWORD|SECRET|CREDENTIAL|KEY", key):
            raise ValueError("transport environment must contain no credentials")
    s = data["scheduler"]
    if s.get("type") != "slurm":
        raise ValueError("this runbook supports Slurm; other schedulers need a reviewed adapter")
    if any(not isinstance(s.get(k), str) or not s[k] for k in ("account", "partition", "operator_user")):
        raise ValueError("scheduler account, partition and operator_user are required")
    st = data["storage"]
    choice(st.get("layout"), ("shared", "node-local"), "storage.layout")
    for key in ("source_root", "install_root", "image_root", "hf_cache", "evidence_root"):
        if not isinstance(st.get(key), str) or not Path(st[key]).is_absolute() or ".." in Path(st[key]).parts:
            raise ValueError(f"storage.{key} must be an absolute path without traversal")
    if len({st[k] for k in ("source_root", "install_root", "evidence_root")}) != 3:
        raise ValueError("source, install and evidence roots must be distinct")
    if set(data["credentials"]) != {"hf_token_file", "ngc_credentials_file"}:
        raise ValueError("credentials contains file references only, no extra fields")
    for value in data["credentials"].values():
        if not isinstance(value, str) or not Path(value).is_absolute() or ".." in Path(value).parts:
            raise ValueError("credential references must be absolute file paths")
    tasks = data.get("workloads")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("workloads must be a nonempty list")
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {"name", "model_size", "dtype", "scale", "repeats", "purpose"}:
            raise ValueError("workload fields differ from the template")
        for key in ("name", "model_size", "dtype"):
            if not isinstance(task.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", task[key]):
                raise ValueError(f"invalid workload {key}")
        positive(task.get("scale"), "workload.scale")
        positive(task.get("repeats"), "workload.repeats")
        if task["scale"] % h["gpus_per_node"] or task["scale"] > len(nodes) * h["gpus_per_node"]:
            raise ValueError("scale must fit the selected whole-node GPU allocation")
        choice(task.get("purpose"), ("diagnostic", "qualification"), "workload.purpose")
    return {"status": "INPUTS_VALID", "node_count": len(nodes), "workload_count": len(tasks),
            "qualification": "not assessed", "next": "verify pinned recipe support and live prerequisites"}


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def inventory(root):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("payload root must be a directory")
    result = []
    forbidden = {".git", ".ssh", "secrets", "token", "stored_tokens", ".credentials", ".netrc", ".env"}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if any(p.lower() in forbidden or p.lower().startswith(".env.") for p in path.relative_to(root).parts):
            raise ValueError(f"credential or private metadata path in payload: {rel}")
        target = path.resolve(strict=True)
        if path.is_symlink() and path.readlink().is_absolute():
            raise ValueError(f"absolute symlink in payload: {rel}")
        if not target.is_relative_to(root):
            raise ValueError(f"external symlink in payload: {rel}")
        if path.is_dir():
            if path.is_symlink():
                raise ValueError(f"directory symlink unsupported: {rel}")
            continue
        if not path.is_file():
            raise ValueError(f"non-regular payload entry: {rel}")
        # Passive text scan only. Large images/packages require the external scanner.
        if path.stat().st_size <= 2_000_000:
            content = path.read_bytes()
            patterns = (rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                        rb"hf_[A-Za-z0-9]{20,}", rb"glpat-[A-Za-z0-9_-]{15,}",
                        rb"xox[baprs]-[A-Za-z0-9-]{15,}")
            if any(re.search(p, content) for p in patterns):
                raise ValueError(f"credential pattern in payload: {rel}")
        entry = {"path": rel, "bytes": path.stat().st_size, "sha256": digest(path),
                 "executable": bool(path.stat().st_mode & 0o111)}
        if path.is_symlink():
            entry["symlink"] = str(path.readlink())
        result.append(entry)
    if not result:
        raise ValueError("payload must contain at least one file")
    return result


def verify(root, manifest):
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
        raise ValueError("unsupported payload manifest")
    seen = set()
    for entry in manifest["files"]:
        name = entry["path"]
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or name in seen:
            raise ValueError("unsafe or duplicate manifest path")
        seen.add(name)
    actual = inventory(root)
    if actual != manifest["files"]:
        raise ValueError("payload inventory differs: file set, content, mode or symlink changed")
    return {"status": "INTEGRITY_VERIFIED", "files": len(actual), "readiness": "not assessed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("validate-config", help="validate non-secret deployment inputs")
    p.add_argument("config", type=Path)
    for cmd in ("manifest", "verify"):
        p = commands.add_parser(cmd)
        p.add_argument("root", type=Path)
        p.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate-config":
            result = validate_config(json.loads(args.config.read_text()))
        elif args.command == "manifest":
            if args.manifest.resolve().is_relative_to(args.root.resolve()):
                raise ValueError("manifest must be stored outside the payload root")
            result = {"schema_version": 1, "files": inventory(args.root)}
            with args.manifest.open("x") as stream:
                json.dump(result, stream, indent=2)
                stream.write("\n")
            result = {"status": "MANIFEST_CREATED", "files": len(result["files"])}
        else:
            result = verify(args.root, json.loads(args.manifest.read_text()))
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Preparation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
