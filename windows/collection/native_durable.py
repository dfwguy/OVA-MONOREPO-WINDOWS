"""Flushed file data and same-volume write-through atomic replacement.

Windows has no portable equivalent of POSIX directory fsync. This implementation
uses MoveFileExW(REPLACE_EXISTING|WRITE_THROUGH), and records that power-loss
qualification of directory metadata remains outside software acceptance.
"""
import os
from pathlib import Path
import tempfile
import time

DURABILITY_PROFILE = {
    'file_data': 'fsync before publication',
    'replacement': 'MoveFileExW REPLACE_EXISTING|WRITE_THROUGH on Windows; os.replace on POSIX',
    'directory_fsync': 'POSIX only; Windows directory metadata power-loss behavior requires site qualification',
    'reboot_or_power_loss_accepted': False,
}


def replace_file(source, destination):
    source, destination = Path(source), Path(destination)
    if os.name != 'nt':
        os.replace(source, destination)
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    move = kernel.MoveFileExW
    move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move.restype = wintypes.BOOL
    deadline = time.monotonic() + 2
    while not move(str(source.resolve()), str(destination.absolute()), 1 | 8):
        error = ctypes.get_last_error()
        if error not in (32, 33) or time.monotonic() >= deadline:
            raise ctypes.WinError(error)
        time.sleep(0.02)


def sync_directory(directory):
    if os.name == 'nt':
        # Explicitly bounded guarantee; never report this as POSIX directory fsync.
        return 'windows-write-through-replacement; directory-powerloss-unqualified'
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data.encode('utf-8') if isinstance(data, str) else data)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(name, path)
        sync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def sync_file(path):
    # Windows FlushFileBuffers requires a writable handle; these are our own outputs.
    with open(path, 'r+b' if os.name == 'nt' else 'rb') as stream:
        stream.flush()
        os.fsync(stream.fileno())
