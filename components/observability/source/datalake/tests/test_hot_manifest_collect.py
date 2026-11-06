from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from hot_manifest_collect import (  # noqa: E402
    discover,
    is_terminal,
    shared_nccl_identity,
    shared_nemo_identity,
)
from runlog_parse import identify  # noqa: E402


class HotManifestDiscoveryTests(unittest.TestCase):
    def test_exact_rack_su1_su14_allowlist(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            wanted = [
                "SU1/rack01/multiNodeNeMo/nemo-26.04.01-49951.out",
                "SU8/rack17/multiNodeMNU/mnubergemm-v-49952.out",
                "SU14/rack24/multiNodeNCCL/nvftp-nccl-five-collective-49953.out",
                "iren_mkz-16k-validation/nemo-26.04.01-49954.out",
                "iren_mkz-16k-validation/nvftp-nccl-five-collective-49955.out",
            ]
            rejected = [
                "SU0/rack01/multiNodeNeMo/nemo-26.04.01-49951.out",
                "SU15/rack24/multiNodeNCCL/nvftp-nccl-five-collective-49953.out",
                "SU1/rack09/multiNodeMNU/mnubergemm-v-49952.out",
                "SU1/rack01/singleNodeMNU/mnubergemm-v-49952.out",
                "SU1/rack01/multiNodeNeMo/job-49951/rank-0.out",
                "iren_mkz-16k-validation/nemo-other-49954.out",
                "iren_mkz-16k-validation/nvftp-nccl-other-49955.out",
            ]
            for rel in wanted + rejected:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n")
            got = {path.relative_to(root).as_posix() for path in discover(root)}
            self.assertEqual(got, set(wanted))

    def test_terminal_markers_are_workload_specific(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "result.out"
            path.write_text("NEMO_VALIDATION_PASS max_steps=30 nodes=18\n")
            self.assertTrue(is_terminal(path, "nemo_single"))
            self.assertFalse(is_terminal(path, "mnubergemm"))
            path.write_text("FIVE_COLLECTIVE_SWEEP_END job=1 rc=0 detail_rc=0\n")
            self.assertTrue(is_terminal(path, "nccl_five_collective"))

    def test_shared_nemo_identity_requires_exact_one_rack_geometry(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "iren_mkz-16k-validation"
            root.mkdir()
            path = root / "nemo-26.04.01-50208.out"
            path.write_text(
                "INFO: nnodes=18\nNODELIST: example50-dh01-b03-[11-18,28-37]\n"
                "NEMO_VALIDATION_PASS max_steps=30 nodes=18\n"
            )
            ident = shared_nemo_identity(path, identify(str(path)))
            self.assertEqual(ident.job_id, "50208")
            self.assertEqual(ident.su, "SU13")
            self.assertEqual(ident.unit_id, "example50-dh01-b03")
            self.assertEqual(ident.workload, "nemo_single")

            path.write_text(
                "INFO: nnodes=18\nNODELIST: example50-dh01-b03-[11-18,28-36]\n"
            )
            ident = shared_nemo_identity(path, identify(str(path)))
            self.assertEqual(ident.harness, "unknown")

    def test_shared_nccl_identity_requires_exact_one_rack_geometry(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "iren_mkz-16k-validation"
            root.mkdir()
            path = root / "nvftp-nccl-five-collective-52332.out"
            trays = [*range(11, 19), *range(28, 38)]
            preflight = "\n".join(
                f"NCCL_IB_PREFLIGHT_READY node=example50-dh02-j06-{tray:02d} rails=4"
                for tray in trays
            )
            path.write_text(
                preflight + "\nFIVE_COLLECTIVE_SWEEP_START job=52332 "
                "nodes=18 gpus=72 racks=dynamic layout=exact-request\n"
                "FIVE_COLLECTIVE_SWEEP_END job=52332 rc=0 detail_rc=0\n"
            )
            ident = shared_nccl_identity(path, identify(str(path)))
            self.assertEqual(ident.job_id, "52332")
            self.assertEqual(ident.su, "SU10")
            self.assertEqual(ident.unit_id, "example50-dh02-j06")
            self.assertEqual(ident.workload, "nccl_five_collective")

            # Cross-rack geometry must never be attributed to one exact rack.
            path.write_text(
                preflight.replace("j06-37", "j17-37")
                + "\nFIVE_COLLECTIVE_SWEEP_START job=52332 "
                "nodes=18 gpus=72 racks=dynamic layout=exact-request\n"
            )
            ident = shared_nccl_identity(path, identify(str(path)))
            self.assertEqual(ident.harness, "unknown")


if __name__ == "__main__":
    unittest.main()
