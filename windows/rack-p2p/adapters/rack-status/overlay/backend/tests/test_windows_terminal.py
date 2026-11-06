# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Native Windows pseudoconsole I/O, without contacting a cluster."""

from __future__ import annotations

import os
import queue
import sys
import time
import unittest

from api import terminal


@unittest.skipUnless(os.name == "nt", "Windows ConPTY requires a native Windows host")
class WindowsTerminalTests(unittest.TestCase):
    def test_interactive_input_output_resize_and_cleanup(self):
        process = terminal._ConPtyProcess(
            [sys.executable, "-u", "-c",
             "import sys; [print('response:' + line.strip(), flush=True) for line in sys.stdin]"],
            os.environ.copy(),
        )
        session = terminal._WindowsTerminalSession("local-test", process, "local-test", "headnode")
        subscriber = session.subscribe()
        try:
            session.write(b"native-terminal-marker\r")
            deadline = time.monotonic() + 10
            received = b""
            while time.monotonic() < deadline and b"response:native-terminal-marker" not in received:
                try:
                    chunk = subscriber.get(timeout=0.1)
                except queue.Empty:
                    continue
                if chunk is None:
                    break
                received += chunk
            self.assertIn(b"response:native-terminal-marker", received)
            session.resize(100, 30)
            session.force_redraw()
            self.assertTrue(session.alive)
        finally:
            session.destroy()
        self.assertIsNotNone(process.poll())
        session.write(b"after-exit\r")
        session.resize(80, 24)


if __name__ == "__main__":
    unittest.main()
