"""Materialize scoped historical LFS inputs for existing verification/build commands.

Native profile dependencies download during normal clone. Complete offline releases
and historical control checks need additional preserved Linux/reference payloads.
No separate cache or credential configuration is introduced here.
"""
import hashlib
from pathlib import Path
import re
import subprocess

POINTER = re.compile(
    rb'version https://git-lfs.github.com/spec/v1\noid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n'
)


def ensure_payloads(root, scopes):
    root = Path(root).resolve()
    pending = []
    for scope in scopes:
        if scope not in {'control', 'components', 'windows', 'artifacts'}:
            raise ValueError('Unsupported payload scope: ' + scope)
        for path in (root / scope).rglob('*'):
            if path.is_symlink():
                continue
            if path.is_file() and path.stat().st_size <= 1024:
                match = POINTER.fullmatch(path.read_bytes())
                if match:
                    pending.append((path, match[1].decode(), int(match[2])))
    if not pending:
        return 0
    if not (root / '.git').exists():
        raise ValueError('LFS pointers require a Git checkout or the complete offline release ZIP.')
    includes = ','.join(scope + '/**' for scope in scopes)
    print(f'Materializing {len(pending)} preserved LFS payloads for this operation.', flush=True)
    result = subprocess.run(
        ['git', '-C', str(root), 'lfs', 'pull', '--include=' + includes, '--exclude='],
        check=False,
    )
    if result.returncode:
        raise ValueError('Git LFS download failed. Use normal GitLab Git/LFS authentication, or the complete offline release ZIP.')
    for path, expected_hash, expected_size in pending:
        if path.stat().st_size != expected_size:
            raise ValueError('LFS payload size mismatch: ' + str(path.relative_to(root)))
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != expected_hash:
            raise ValueError('LFS payload hash mismatch: ' + str(path.relative_to(root)))
    return len(pending)
