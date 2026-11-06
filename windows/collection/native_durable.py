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


def replace_file(source, destination, *, retry_owned_target=False):
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
    last_error = None
    while True:
        if last_error is not None and time.monotonic() >= deadline:
            raise ctypes.WinError(last_error)
        if move(str(source.resolve()), str(destination.absolute()), 1 | 8):
            return
        error = ctypes.get_last_error()
        # Error5 may be transient when a reader omitted FILE_SHARE_DELETE.
        # Scope that retry to our own same-directory mkstemp replacement of an
        # existing writable regular file. Never alter ACLs, unlink the target,
        # retry a read-only target or turn a permanent denial into success.
        owned_existing = (retry_owned_target and destination.is_file()
            and not destination.is_symlink()
            and source.parent.resolve() == destination.parent.resolve()
            and source.name.startswith('.' + destination.name + '-')
            and os.access(destination, os.W_OK))
        transient = error in (32, 33) or (error == 5 and owned_existing)
        if not transient or time.monotonic() >= deadline:
            raise ctypes.WinError(error)
        last_error = error
        time.sleep(min(0.02, max(0, deadline-time.monotonic())))


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
        replace_file(name, path, retry_owned_target=True)
        sync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def sync_file(path):
    # Windows FlushFileBuffers requires a writable handle; these are our own outputs.
    with open(path, 'r+b' if os.name == 'nt' else 'rb') as stream:
        stream.flush()
        os.fsync(stream.fileno())


def read_atomic_text(path):
    """Read a stable file while allowing another process to atomically rename it."""
    if os.name != 'nt':
        return Path(path).read_text(encoding='utf-8')
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # GENERIC_READ; FILE_SHARE_READ|WRITE|DELETE; OPEN_EXISTING; NORMAL.
    handle = create(str(Path(path).absolute()), 0x80000000, 7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    # open_osfhandle transfers ownership; closing this stream closes the HANDLE.
    with os.fdopen(descriptor, 'rb') as stream:
        return stream.read().decode('utf-8')
