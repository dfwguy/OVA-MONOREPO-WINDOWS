# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Process-shared file locks for the existing document stores and worker leases.

POSIX keeps its native flock implementation. Windows uses kernel byte-range locks,
including shared readers and nonblocking claims; closing a handle releases its lock.
Lock files must stay on local storage shared by all processes using the same store.
"""

from __future__ import annotations

import os

if os.name != "nt":
    from fcntl import LOCK_EX, LOCK_NB, LOCK_SH, LOCK_UN, flock
else:
    import ctypes
    import errno
    import msvcrt
    from ctypes import wintypes

    LOCK_SH = 1
    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    class _Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _lock_file = _kernel32.LockFileEx
    _lock_file.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_Overlapped),
    ]
    _lock_file.restype = wintypes.BOOL
    _unlock_file = _kernel32.UnlockFileEx
    _unlock_file.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, ctypes.POINTER(_Overlapped),
    ]
    _unlock_file.restype = wintypes.BOOL

    def flock(file, operation: int) -> None:
        """Lock the first byte without changing file contents or its seek position.

        Every participant locks the same byte, even in an empty sidecar. Windows
        permits a lock beyond EOF, so read-only handles need no initialization write.
        """
        fd = file if isinstance(file, int) else file.fileno()
        handle = msvcrt.get_osfhandle(fd)
        overlapped = _Overlapped()
        if operation == LOCK_UN:
            ok = _unlock_file(handle, 0, 1, 0, ctypes.byref(overlapped))
        else:
            kind = operation & ~LOCK_NB
            if kind not in (LOCK_SH, LOCK_EX):
                raise ValueError("Expected LOCK_SH, LOCK_EX or LOCK_UN")
            flags = (2 if kind == LOCK_EX else 0) | (1 if operation & LOCK_NB else 0)
            ok = _lock_file(handle, flags, 0, 1, 0, ctypes.byref(overlapped))
        if not ok:
            code = ctypes.get_last_error()
            if code == 33:  # ERROR_LOCK_VIOLATION, matching flock's busy contract.
                raise BlockingIOError(errno.EAGAIN, "File lock is held by another process")
            raise ctypes.WinError(code)


__all__ = ["LOCK_EX", "LOCK_NB", "LOCK_SH", "LOCK_UN", "flock"]
