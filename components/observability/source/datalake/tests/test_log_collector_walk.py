from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import log_collector  # noqa: E402


class CollectorWalkPriorityTests(unittest.TestCase):
    def test_acceptance_evidence_precedes_newer_raw_and_debug_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final = root / "nvftp-nccl-five-collective-20146.out"
            summary = root / "summary.tsv"
            debug = root / "rank0.log"
            raw = root / "test-3-sendrecv.raw"
            for index, path in enumerate((final, summary, debug, raw), 1):
                path.write_text(path.name, encoding="utf-8")
                os.utime(path, (index, index))

            self.assertEqual(
                list(log_collector.walk(str(root))),
                [str(final), str(summary), str(debug), str(raw)],
            )


if __name__ == "__main__":
    unittest.main()
