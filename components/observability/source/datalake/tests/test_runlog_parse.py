from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from runlog_parse import ActivityResolver, identify  # noqa: E402


class NvftpFiveCollectiveIdentityTests(unittest.TestCase):
    def test_stdout_has_job_and_canonical_rack(self):
        item = identify(
            "/logs/rackstatus/SU12/rack02/singleRackNCCL/"
            "nvftp-nccl-five-collective-6979.out",
            cluster="IREN_MKZ-16K",
            mtime=1,
        )
        self.assertEqual(item.job_id, "6979")
        self.assertEqual(item.harness, "rackstatus")
        self.assertEqual(item.workload, "nccl_five_collective")
        self.assertEqual(item.unit_kind, "rack")
        self.assertEqual(item.unit_id, "example50-dh01-a02")
        self.assertEqual(item.su, "SU12")
        self.assertEqual(item.stream, "sbatch_stdout")
        self.assertTrue(item.run_id.endswith("-j6979"))

    def test_summary_in_job_directory_joins_same_job_and_rack(self):
        item = identify(
            "/logs/rackstatus/SU12/rack02/singleRackNCCL/job-6979/summary.tsv",
            cluster="IREN_MKZ-16K",
            mtime=1,
        )
        self.assertEqual(item.job_id, "6979")
        self.assertEqual(item.workload, "nccl_five_collective")
        self.assertEqual(item.unit_id, "example50-dh01-a02")
        self.assertEqual(item.su, "SU12")
        self.assertEqual(item.stream, "summary_tsv")
        self.assertTrue(item.run_id.endswith("-j6979"))

    def test_su14_maps_to_dh01_c(self):
        item = identify(
            "/logs/rackstatus/SU14/rack24/singleRackNCCL/"
            "nvftp-nccl-five-collective-7000.out",
            cluster="IREN_MKZ-16K",
            mtime=1,
        )
        self.assertEqual(item.unit_id, "example50-dh01-c24")
        self.assertEqual(item.su, "SU14")

    def test_per_test_live_logs_join_canonical_rack_run(self):
        base = "/logs/rackstatus/SU12/rack02/singleRackNCCL/job-6982/"
        live = identify(base + "test-1-all_reduce-8k-32g.live.log", mtime=1)
        info = identify(base + "test-1-all_reduce-nccl-info.live.log", mtime=1)
        raw = identify(base + "test-1-all_reduce-8k-32g.raw", mtime=1)
        for item in (live, info, raw):
            self.assertEqual(item.job_id, "6982")
            self.assertEqual(item.harness, "rackstatus")
            self.assertEqual(item.workload, "nccl_five_collective")
            self.assertEqual(item.unit_id, "example50-dh01-a02")
            self.assertEqual(item.su, "SU12")
            self.assertTrue(item.run_id.endswith("-j6982"))
        self.assertEqual(live.stream, "job_step_stdout")
        self.assertEqual(info.stream, "nccl_rank_debug")
        self.assertEqual(raw.stream, "job_step_stdout")


class ActivityResolverTests(unittest.TestCase):
    def test_scheduler_reference_is_authoritative(self):
        resolver = ActivityResolver({
            "old": {
                "activity_id": "activity-old", "phase": "error",
                "log_dir": "/cluster/OVA/logs/SU12/rack02/singleRackNCCL",
                "created_at": "2026-08-28T15:39:11+00:00",
                "tasks": [{"scheduler_ref": "6979"}],
            },
            "new": {
                "activity_id": "activity-new", "phase": "running",
                "log_dir": "/cluster/OVA/logs/SU12/rack02/singleRackNCCL",
                "created_at": "2026-08-28T15:42:48+00:00",
            },
        })
        path = ("/logs/rackstatus/SU12/rack02/singleRackNCCL/"
                "nvftp-nccl-five-collective-6979.out")
        item = identify(path, mtime=1)
        self.assertEqual(resolver.resolve(item, path, 1787932000), "activity-old")

    def test_live_activity_falls_back_to_exact_log_root(self):
        activity_id = "cf4d1eb1-c4ae-4d2c-bcf3-34fc9a736a3c"
        resolver = ActivityResolver({
            "live": {
                "activity_id": activity_id, "phase": "running",
                "log_dir": "/cluster/OVA/logs/SU12/rack02/singleRackNCCL",
                "created_at": "2026-08-28T15:42:48+00:00",
            },
        })
        path = "/logs/rackstatus/SU12/rack02/singleRackNCCL/job-6980/summary.tsv"
        item = identify(path, mtime=1)
        self.assertEqual(resolver.resolve(item, path, 1787931811), activity_id)

    def test_completed_activity_without_scheduler_ref_is_not_guessed(self):
        resolver = ActivityResolver({
            "done": {
                "activity_id": "done", "phase": "error",
                "log_dir": "/cluster/OVA/logs/SU12/rack02/singleRackNCCL",
                "created_at": "2026-08-28T15:42:48+00:00",
            },
        })
        path = "/logs/rackstatus/SU12/rack02/singleRackNCCL/job-6980/summary.tsv"
        self.assertEqual(resolver.resolve(identify(path, mtime=1), path, 1787931811), "")


class NvftpNemoIdentityTests(unittest.TestCase):
    def test_standard_stdout_has_job_su_and_canonical_rack(self):
        path = ("/logs/rackstatus/SU12/rack21/singleRackNeMo/"
                "nemo-26.04.01-8768.out")
        item = identify(path, cluster="IREN_MKZ-16K", mtime=1)
        self.assertEqual(item.job_id, "8768")
        self.assertEqual(item.harness, "rackstatus")
        self.assertEqual(item.workload, "nemo_single")
        self.assertEqual(item.unit_kind, "rack")
        self.assertEqual(item.unit_id, "example50-dh01-a21")
        self.assertEqual(item.su, "SU12")
        self.assertEqual(item.stream, "sbatch_stdout")
        self.assertEqual(
            item.run_id,
            "IREN_MKZ-16K-rackstatus-nemo_single-example50-dh01-a21-j8768",
        )

    def test_multinode_stdout_has_job_su_and_canonical_rack(self):
        path = ("/logs/rackstatus/SU13/rack22/multiNodeNeMo/"
                "nemo-26.04.01-17769.out")
        item = identify(path, cluster="IREN_MKZ-16K", mtime=1)
        self.assertEqual(item.job_id, "17769")
        self.assertEqual(item.harness, "rackstatus")
        self.assertEqual(item.workload, "nemo_single")
        self.assertEqual(item.unit_kind, "rack")
        self.assertEqual(item.unit_id, "example50-dh01-b22")
        self.assertEqual(item.su, "SU13")
        self.assertEqual(item.stream, "sbatch_stdout")
        self.assertEqual(
            item.run_id,
            "IREN_MKZ-16K-rackstatus-nemo_single-example50-dh01-b22-j17769",
        )

    def test_scheduler_reference_links_terminal_activity(self):
        activity_id = "89007449-03c1-4898-bca0-427be7c25dd8"
        resolver = ActivityResolver({activity_id: {
            "phase": "error",
            "log_dir": "/cluster/OVA/logs/SU12/rack21/singleRackNeMo",
            "tasks": [{"scheduler_ref": "8768"}],
        }})
        path = ("/logs/rackstatus/SU12/rack21/singleRackNeMo/"
                "nemo-26.04.01-8768.out")
        item = identify(path, cluster="IREN_MKZ-16K", mtime=1)
        self.assertEqual(resolver.resolve(item, path, 1787951151), activity_id)


class NvftpMnubergemmIdentityTests(unittest.TestCase):
    def test_exact_rack_stdout_has_job_su_and_canonical_rack(self):
        path = ("/logs/rackstatus/SU9/rack04/multiNodeMNU/"
                "mnubergemm-26.03-v1.17-g001-24646.out")
        item = identify(path, cluster="IREN_MKZ-16K", mtime=1)
        self.assertEqual(item.job_id, "24646")
        self.assertEqual(item.harness, "rackstatus")
        self.assertEqual(item.workload, "mnubergemm")
        self.assertEqual(item.unit_kind, "rack")
        self.assertEqual(item.unit_id, "example50-dh02-i04")
        self.assertEqual(item.su, "SU9")
        self.assertEqual(item.stream, "sbatch_stdout")
        self.assertEqual(
            item.run_id,
            "IREN_MKZ-16K-rackstatus-mnubergemm-example50-dh02-i04-j24646",
        )


if __name__ == "__main__":
    unittest.main()
