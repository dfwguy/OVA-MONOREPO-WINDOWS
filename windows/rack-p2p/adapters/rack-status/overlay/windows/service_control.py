# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Signal the native server's service-local graceful shutdown event."""
import os

import win32con
import win32event

if __name__ == "__main__":
    event = win32event.OpenEvent(
        win32con.EVENT_MODIFY_STATE,
        False,
        os.environ.get("NVIS_WINDOWS_STOP_EVENT", "Local\\NVISRackStatusStop"),
    )
    try:
        win32event.SetEvent(event)
    finally:
        event.Close()
