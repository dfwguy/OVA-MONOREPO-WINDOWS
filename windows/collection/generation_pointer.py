"""Publish/pin immutable Parquet generations without Windows symlink privileges."""
import hashlib
import json
from pathlib import Path
import re
from native_durable import atomic_write


def publish_generation(lake, generation):
    lake, generation = Path(lake).resolve(), Path(generation).resolve()
    if generation.parent != lake or not re.fullmatch(r'generation-[A-Za-z0-9]+', generation.name):
        raise ValueError('Generation must be a directly contained, named lake generation.')
    manifest = generation / 'manifest.json'
    record = {'schema_version': 1, 'generation': generation.name,
              'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}
    atomic_write(lake / 'current.json', json.dumps(record, sort_keys=True) + '\n')


def resolve_generation(lake):
    lake = Path(lake).resolve()
    record = json.loads((lake / 'current.json').read_text(encoding='utf-8'))
    name = record['generation']
    if not re.fullmatch(r'generation-[A-Za-z0-9]+', name):
        raise ValueError('Invalid generation pointer.')
    generation = (lake / name).resolve()
    if generation.parent != lake or not generation.is_dir():
        raise ValueError('Generation escaped the lake or is missing.')
    actual = hashlib.sha256((generation / 'manifest.json').read_bytes()).hexdigest()
    if actual != record['manifest_sha256']:
        raise ValueError('Generation manifest changed after publication.')
    return generation
