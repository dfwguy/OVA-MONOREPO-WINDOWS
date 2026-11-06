#!/usr/bin/env python3
"""Safely extract a tool ZIP to a NEW directory, retaining Linux executable bits."""
import argparse
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile
import re

def unpack(archive, destination):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError('Destination must not already exist; choose a new release directory.')
    with zipfile.ZipFile(archive) as z:
        seen = set()
        prefixes = {}
        for info in z.infolist():
            path = PurePosixPath(info.filename)
            raw_parts = info.filename.rstrip('/').split('/')
            mode = info.external_attr >> 16
            if (not path.parts or path.is_absolute() or '..' in path.parts or '\\' in info.filename
                    or ':' in info.filename or stat.S_ISLNK(mode)):
                raise ValueError(f'Unsafe archive member: {info.filename}')
            for part in raw_parts:
                if (not part or part in ('.', '..') or part.endswith(('.', ' '))
                        or any(ord(c) < 32 or c in '<>"|?*' for c in part)
                        or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I)):
                    raise ValueError(f'Non-portable archive path: {info.filename}')
            for length in range(1, len(path.parts) + 1):
                prefix = '/'.join(path.parts[:length])
                key = prefix.casefold()
                if key in prefixes and prefixes[key] != prefix:
                    raise ValueError(f'Case-colliding archive path: {info.filename}')
                prefixes[key] = prefix
            key = path.as_posix().casefold()
            if key in seen:
                raise ValueError(f'Duplicate/case-colliding member: {info.filename}')
            seen.add(key)
            if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError(f'Unsupported archive member: {info.filename}')
        destination.mkdir(parents=True)
        for info in z.infolist():
            target = destination.joinpath(*PurePosixPath(info.filename).parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as source, target.open('wb') as out:
                    shutil.copyfileobj(source, out)
                if __import__('os').name == 'posix':
                    target.chmod((info.external_attr >> 16 & 0o777) or 0o644)
    print(f'Extracted {archive} to {destination}; no services started.')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive', type=Path)
    p.add_argument('destination', type=Path)
    a = p.parse_args()
    unpack(a.archive, a.destination)
