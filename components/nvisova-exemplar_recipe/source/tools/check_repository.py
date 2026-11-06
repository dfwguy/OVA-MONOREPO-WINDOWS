#!/usr/bin/env python3
"""Check the tracked publication tree without reading private deployment files."""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = {
    "site identifier": r"(?i)\bs[t]n\b|edc[0-9]{3}|od[0-9]-|nvidia-s[s]h|/s[t]n-disk|/cluster/O[V]A|nscale[t]x|\bs[u]1\b",
    "historical job": r"(?i)\bjob[0-9]+\b|reference/jo[b]",
    "private address": r"\b(?:10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3}|172\.(?:1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3})\b",
    "private key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "token": r"hf_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{15,}|xox[baprs]-[A-Za-z0-9-]{15,}",
}


def check():
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    findings = []
    count = 0
    for name in filter(None, files):
        path = ROOT / name
        if not path.exists():
            findings.append(f"tracked file missing: {name}")
            continue
        count += 1
        if path.is_symlink():
            findings.append(f"unexpected publication symlink: {name}")
            continue
        if name.endswith((".tar.gz", ".tar.zst", ".tar", ".sqsh", ".squashfs", ".bundle")):
            findings.append(f"unexpected embedded payload: {name}")
            continue
        try:
            content = path.read_text()
        except UnicodeDecodeError:
            findings.append(f"unexpected binary file: {name}")
            continue
        for label, pattern in POLICY.items():
            if re.search(pattern, content) or re.search(pattern, name):
                findings.append(f"{label}: {name}")
        if path.suffix == ".md":
            # Validate local paths in ordinary links and HTML banner image sources.
            targets = re.findall(r"\]\(([^)\s]+)(?:\s+[^)]*)?\)", content)
            targets += re.findall(r'<img\s+[^>]*src="([^"]+)"', content)
            for target in targets:
                if re.match(r"https?://|mailto:|#", target):
                    continue
                target = target.split("#", 1)[0]
                if target and not (path.parent / target).is_file():
                    findings.append(f"broken local link: {name} -> {target}")
    return {"status": "FAILED" if findings else "PASSED", "tracked_files": count,
            "findings": findings, "scope": "tracked publication tree; history and live cluster not assessed"}


if __name__ == "__main__":
    report = check()
    print(json.dumps(report, indent=2))
    sys.exit(bool(report["findings"]))
