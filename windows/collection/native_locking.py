"""Exclusive interprocess file locks: LockFileEx on Windows, flock on POSIX."""
import errno
import os

LOCK_EX, LOCK_NB, LOCK_UN = 2, 4, 8

if os.name == 'nt':
    import ctypes
    import msvcrt
    from ctypes import wintypes
    class OVERLAPPED(ctypes.Structure):
        _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                    ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD), ('hEvent', wintypes.HANDLE)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LockFileEx.argtypes = [wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(OVERLAPPED)]
    kernel.LockFileEx.restype = wintypes.BOOL
    kernel.UnlockFileEx.argtypes = [wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(OVERLAPPED)]
    kernel.UnlockFileEx.restype = wintypes.BOOL


def flock(file_descriptor, operation):
    """Lock byte zero; the OS also releases the lock when the handle/process closes."""
    if operation not in (LOCK_EX, LOCK_EX | LOCK_NB, LOCK_UN):
        raise ValueError('Only exclusive, nonblocking-exclusive and unlock are supported.')
    if os.name != 'nt':
        import fcntl
        return fcntl.flock(file_descriptor, operation)
    handle = msvcrt.get_osfhandle(file_descriptor)
    overlapped = OVERLAPPED()
    if operation == LOCK_UN:
        okay = kernel.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped))
    else:
        flags = 2 | (1 if operation & LOCK_NB else 0)
        okay = kernel.LockFileEx(handle, flags, 0, 1, 0, ctypes.byref(overlapped))
    if not okay:
        error = ctypes.get_last_error()
        if operation & LOCK_NB and error in (32, 33):
            raise BlockingIOError(errno.EAGAIN, 'Another process holds the evidence lock.')
        raise ctypes.WinError(error)
