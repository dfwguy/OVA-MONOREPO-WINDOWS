from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lake_result_map import (  # noqa: E402
    campaign_verdict_from_file,
    campaign_workload,
    iter_campaign_result_paths,
    parse_campaign_nccl,
)
from lake_run_backfill import parse_llama_nemo, parse_mnubergemm  # noqa: E402


NCCL_PASS = """\
FIVE_COLLECTIVE_SWEEP_START job=19051 nodes=18 gpus=72
TEST_END test=1 collective=all_reduce rc=0 correctness=OK
TEST_END test=2 collective=alltoall rc=0 correctness=OK
TEST_END test=3 collective=sendrecv rc=0 correctness=OK
TEST_END test=4 collective=all_gather rc=0 correctness=OK
TEST_END test=5 collective=reduce_scatter rc=0 correctness=OK
FIVE_COLLECTIVE_SWEEP_END job=19051 rc=0 detail_rc=0
"""

NEMO_PASS = """\
 [2026-08-29 22:43:25] iteration 29/30 | elapsed time per iteration (ms): 4587.6 | number of nan iterations: 0 |
Step Time : 4.58s GPU utilization: 1799.3MODEL_TFLOP/s/GPU
 [2026-08-29 22:43:30] iteration 30/30 | elapsed time per iteration (ms): 4580.7 | number of nan iterations: 0 |
Step Time : 4.57s GPU utilization: 1802.3MODEL_TFLOP/s/GPU
NEMO_VALIDATION_PASS max_steps=30 nodes=18
"""

MNU_PASS = """\
HOSTLIST: example50-dh02-i17-18
MNUB [I] G: 0 example50-dh02-i17-18 L: 0 GFlops:7.8743e+05
MNUB [I] G: 0 example50-dh02-i17-18 L: 0 returning QUAL_OK
MNUB [I] G: 1 example50-dh02-i17-18 L: 1 returning QUAL_OK
MNUB [I] G: 2 example50-dh02-i17-18 L: 2 returning QUAL_OK
MNUB [I] G: 3 example50-dh02-i17-18 L: 3 returning QUAL_OK
MNUB [I] G: 0 example50-dh02-i17-18 L: 0 normal mpi teardown
"""


def strict_verdict(workload, parser, text, state="COMPLETED"):
    result, ok, reason = parser(text)
    verdict = campaign_verdict_from_file(
        workload, result, ok, reason, state, text)
    return verdict, result


class CampaignDiscoveryTests(unittest.TestCase):
    def test_only_authoritative_su1_su14_main_outputs_are_discovered(self):
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            wanted = [
                "SU1/rack01/multiNodeNeMo/nemo-26.04.01-49951.out",
                "SU8/rack17/singleNodeMNU/mnubergemm-26.03-18789.out",
                "SU9/rack17/singleNodeMNU/mnubergemm-26.03-v1.17-g001-18789.out",
                "SU9/rack04/multiNodeNeMo/nemo-26.04.01-19032.out",
                "iren_mkz-16k-validation/nemo-26.04.01-50208.out",
                "SU14/rack24/singleNodeNCCL/nvftp-nccl-five-collective-19051.out",
                "SU10/rack03/singleNodeNeMo/sn-llama/"
                "rack-status-NEMO-56B-30STEPS-1N-example50-dh02-j03-11-17001.txt",
            ]
            rejected = [
                # Outside the supported campaign and rack universe.
                "SU0/rack17/singleNodeMNU/mnubergemm-26.03-18789.out",
                "SU15/rack17/singleNodeMNU/mnubergemm-26.03-18789.out",
                "SU9/rack09/singleNodeMNU/mnubergemm-26.03-18789.out",
                # Non-authoritative staging and per-test/detail artifacts.
                "SU9/rack17/singleNodeMNU/validation-container-stage-18789.out",
                "SU9/rack04/multiNodeNeMo/job-19032/rank-0.out",
                "SU14/rack24/singleNodeNCCL/job-19051/"
                "test-1-all_reduce-8k-32g.raw",
                "SU14/rack24/singleNodeNCCL/"
                "nvftp-nccl-five-collective-19051.out.bak",
                # A plausible name in the wrong validation directory.
                "SU9/rack17/manual/mnubergemm-26.03-18789.out",
            ]
            for rel in wanted + rejected:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n")
            got = {Path(p).relative_to(root).as_posix()
                   for p in iter_campaign_result_paths(str(root))}
            self.assertEqual(got, set(wanted))

    def test_workload_is_derived_from_allowlisted_directory(self):
        self.assertEqual(campaign_workload(
            "/x/SU9/rack17/singleNodeMNU/mnubergemm-v-18789.out")[0],
            "mnubergemm")
        self.assertEqual(campaign_workload(
            "/x/SU9/rack04/multiNodeNeMo/nemo-v-19032.out")[0], "nemo")
        self.assertEqual(campaign_workload(
            "/x/iren_mkz-16k-validation/nemo-26.04.01-50208.out")[0], "nemo")
        self.assertEqual(campaign_workload(
            "/x/SU9/rack04/multiNodeNCCL/"
            "nvftp-nccl-five-collective-19051.out")[0], "nccl")


class CampaignStrictVerdictTests(unittest.TestCase):
    def test_nccl_requires_all_five_correct_tests_terminal_and_slurm(self):
        (verdict, _), result = strict_verdict(
            "nccl", parse_campaign_nccl, NCCL_PASS)
        self.assertEqual(verdict, "PASS")
        self.assertEqual(result["collectives"], 5)

        incomplete = NCCL_PASS.replace(
            "TEST_END test=5 collective=reduce_scatter rc=0 correctness=OK\n", "")
        (verdict, _), _ = strict_verdict(
            "nccl", parse_campaign_nccl, incomplete)
        self.assertEqual(verdict, "PARTIAL")

        failed = NCCL_PASS.replace("collective=sendrecv rc=0 correctness=OK",
                                   "collective=sendrecv rc=1 correctness=FAIL")
        (verdict, _), _ = strict_verdict("nccl", parse_campaign_nccl, failed)
        self.assertEqual(verdict, "FAIL")

        (verdict, detail), _ = strict_verdict(
            "nccl", parse_campaign_nccl, NCCL_PASS, "RUNNING")
        self.assertEqual(verdict, "PARTIAL")
        self.assertIn("Slurm says RUNNING", detail)

    def test_nemo_requires_explicit_matching_pass_marker_and_slurm(self):
        (verdict, _), result = strict_verdict(
            "nemo", parse_llama_nemo, NEMO_PASS)
        self.assertEqual(verdict, "PASS")
        self.assertEqual(result["validation_nodes"], 18)

        no_marker = NEMO_PASS.replace(
            "NEMO_VALIDATION_PASS max_steps=30 nodes=18\n", "")
        (verdict, _), _ = strict_verdict(
            "nemo", parse_llama_nemo, no_marker)
        self.assertEqual(verdict, "PARTIAL")

        wrong_steps = NEMO_PASS.replace("max_steps=30", "max_steps=31")
        (verdict, _), _ = strict_verdict(
            "nemo", parse_llama_nemo, wrong_steps)
        self.assertEqual(verdict, "PARTIAL")

        failed = NEMO_PASS + "NEMO_VALIDATION_FAIL stage=train rc=1\n"
        (verdict, _), _ = strict_verdict(
            "nemo", parse_llama_nemo, failed)
        self.assertEqual(verdict, "FAIL")

    def test_mnu_requires_four_unique_gpu_qual_ok_per_host_and_teardown(self):
        (verdict, _), result = strict_verdict(
            "mnubergemm", parse_mnubergemm, MNU_PASS)
        self.assertEqual(verdict, "PASS")
        self.assertEqual(result["qual_ok_count"], 4)

        missing_gpu = MNU_PASS.replace(
            "MNUB [I] G: 3 example50-dh02-i17-18 L: 3 returning QUAL_OK\n", "")
        (verdict, _), _ = strict_verdict(
            "mnubergemm", parse_mnubergemm, missing_gpu)
        self.assertEqual(verdict, "PARTIAL")

        no_teardown = MNU_PASS.replace(
            "MNUB [I] G: 0 example50-dh02-i17-18 L: 0 normal mpi teardown\n", "")
        (verdict, _), _ = strict_verdict(
            "mnubergemm", parse_mnubergemm, no_teardown)
        self.assertEqual(verdict, "PARTIAL")

        failed = MNU_PASS.replace("returning QUAL_OK", "returning QUAL_RUNTIME_ERROR", 1)
        (verdict, _), _ = strict_verdict(
            "mnubergemm", parse_mnubergemm, failed)
        self.assertEqual(verdict, "FAIL")


if __name__ == "__main__":
    unittest.main()
