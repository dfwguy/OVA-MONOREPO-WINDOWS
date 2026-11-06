"""Build the pinned preparation helper for a Windows control host.

Destination paths in an Exemplar deployment config refer to Linux. Local payload
inventory paths remain native to the machine running this helper.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "components/nvisova-exemplar_recipe/source/tools/prepare.py"


def build(output):
    raw = SOURCE.read_bytes()
    # Pin the supplied toolkit manifest before applying the two path-only edits.
    manifest = json.loads((ROOT / "components/nvisova-exemplar_recipe/FILE_MANIFEST.json").read_text())
    entries = manifest["files"]
    if isinstance(entries, dict):
        entries = [dict(path=k, **v) for k, v in entries.items()]
    expected = next(x["sha256"] for x in entries if x["path"] == "source/tools/prepare.py")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Pinned Exemplar helper differs; review the adapter before rebuilding")
    source = raw.decode("utf-8")
    edits = {
        'not Path(st[key]).is_absolute() or ".." in Path(st[key]).parts':
        'not PurePosixPath(st[key]).is_absolute() or ".." in PurePosixPath(st[key]).parts',
        'not Path(value).is_absolute() or ".." in Path(value).parts':
        'not PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts',
    }
    for old, new in edits.items():
        if source.count(old) != 1:
            raise ValueError("Expected path-validation expression changed")
        source = source.replace(old, new)
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=False)
    target = destination / "prepare.py"
    target.write_text(source, encoding="utf-8", newline="\n")
    record = {"schema_version": 1, "source_sha256": expected,
              "output_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
              "changes": "Validate remote Linux destination paths with PurePosixPath; retain native local inventory paths",
              "qualification": "Preparation helper only; not GPU or official recipe runtime acceptance"}
    (destination / "BUILD_PROVENANCE.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="A fresh directory outside the repository")
    print(json.dumps(build(parser.parse_args().output), indent=2))
