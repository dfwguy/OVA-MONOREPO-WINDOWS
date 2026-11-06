# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Exercise kernel locks with independent processes, including abrupt worker exit."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import file_lock

BACKEND = Path(__file__).resolve().parents[1]
PROBE = """
import sys
import file_lock
with open(sys.argv[1], 'a+') as handle:
    kind = file_lock.LOCK_SH if sys.argv[2] == 'shared' else file_lock.LOCK_EX
    try:
        file_lock.flock(handle, kind | file_lock.LOCK_NB)
    except BlockingIOError:
        sys.exit(23)
    file_lock.flock(handle, file_lock.LOCK_UN)
"""


class FileLockTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.lock"
        self.environment = {**os.environ, "PYTHONPATH": str(BACKEND)}

    def probe(self, kind="exclusive"):
        return subprocess.run(
            [sys.executable, "-c", PROBE, str(self.path), kind],
            env=self.environment, capture_output=True, text=True, timeout=15, check=False,
        )

    def test_exclusive_lock_excludes_another_process_and_unlock_releases_it(self):
        with self.path.open("a+") as handle:
            file_lock.flock(handle, file_lock.LOCK_EX)
            self.assertEqual(self.probe().returncode, 23)
            self.assertEqual(self.probe("shared").returncode, 23)
            file_lock.flock(handle.fileno(), file_lock.LOCK_UN)
            self.assertEqual(self.probe().returncode, 0)

    def test_shared_readers_coexist_and_exclude_a_writer(self):
        with self.path.open("a+") as handle:
            file_lock.flock(handle, file_lock.LOCK_SH)
            self.assertEqual(self.probe("shared").returncode, 0)
            self.assertEqual(self.probe().returncode, 23)
            file_lock.flock(handle, file_lock.LOCK_UN)

    def test_process_death_releases_a_worker_claim(self):
        program = """
import sys
import file_lock
handle = open(sys.argv[1], 'a+')
file_lock.flock(handle, file_lock.LOCK_EX)
print('locked', flush=True)
sys.stdin.readline()
"""
        worker = subprocess.Popen(
            [sys.executable, "-c", program, str(self.path)], env=self.environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(worker.stdout.readline().strip(), "locked")
            self.assertEqual(self.probe().returncode, 23)
            worker.kill()
            worker.communicate(timeout=10)
            self.assertEqual(self.probe().returncode, 0)
        finally:
            if worker.poll() is None:
                worker.kill()
            worker.communicate(timeout=10)

    def test_document_writers_do_not_lose_updates_or_replace_an_open_windows_file(self):
        import json_db

        path = Path(self.directory.name) / "state.json"
        json_db.atomic_write_json(path, {"count": 0})
        program = """
import sys
from json_db import AtomicJSONStorage, exclusive_lock
storage = AtomicJSONStorage(sys.argv[1])
for _ in range(50):
    with exclusive_lock(sys.argv[1]):
        document = storage.read()
        document['count'] += 1
        storage.write(document)
"""
        workers = [subprocess.Popen(
            [sys.executable, "-c", program, str(path)], env=self.environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ) for _ in range(4)]
        try:
            for worker in workers:
                _, errors = worker.communicate(timeout=30)
                self.assertEqual(worker.returncode, 0, errors)
            self.assertEqual(json_db.AtomicJSONStorage(str(path)).read(), {"count": 200})
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.kill()
                    worker.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
