from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lake_job_census import result_path_from_submitline  # noqa: E402


class JobCensusPathTests(unittest.TestCase):
    def test_slurm_job_token_is_resolved(self):
        line = (
            "sbatch --output=/cluster/OVA/logs/iren_mkz-16k-validation/"
            "nemo-26.04.01-%j.out workload.sh"
        )
        self.assertEqual(
            result_path_from_submitline(line, "50208"),
            "/cluster/OVA/logs/iren_mkz-16k-validation/nemo-26.04.01-50208.out",
        )


if __name__ == "__main__":
    unittest.main()
