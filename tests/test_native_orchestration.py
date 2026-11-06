"""Portable tests also executed by native Windows Python; no live transport."""
import importlib.util
import json
import multiprocessing
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows/auto-action"))
import controller


def confirmed_result(argv, payload=b"fixture preview"):
    marker = re.search(r"OVA_REMOTE_DONE:[a-f0-9]{32}", argv[-1]).group(0).encode()
    return subprocess.CompletedProcess(argv, 0, payload + b"\n" + marker + b"\n", b"")


def holding_cycle(config, ready, release):
    def runner(*args, **kwargs):
        ready.set()
        if not release.wait(10):
            raise RuntimeError("Test worker was not released")
        return confirmed_result(args[0])
    controller.cycle(config, runner)


class NativeAutoAction(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / "site.json"
        self.value = {"schema_version": 1, "ssh_alias": "fixture-controller", "node": "fixture-node",
                      "test": "fixture-test", "remote_root": "/opt/reviewed bringup",
                      "fanout": "clush", "state_directory": str(self.directory / "private-state"),
                      "mode": "preview", "execute_authorized": False,
                      "launcher_sha256": "a" * 64, "timeout_seconds": 30}

    def config(self):
        self.path.write_text(json.dumps(self.value))
        return controller.load_config(self.path)

    def test_one_node_scope_and_explicit_authorization(self):
        for field, value in [("node", "node[1-3]"), ("node", "node-a,node-b"),
                             ("ssh_alias", "-oProxyCommand=bad"), ("test", "bad;command"),
                             ("remote_root", "/tmp/../other"), ("schema_version", True)]:
            with self.subTest(field=field, value=value):
                original = self.value[field]
                self.value[field] = value
                with self.assertRaises(ValueError):
                    self.config()
                self.value[field] = original
        self.value["mode"] = "execute"
        with self.assertRaisesRegex(ValueError, "authorization"):
            self.config()

    def test_remote_shell_boundaries_preserve_hash_and_preview(self):
        for fanout in ("clush", "pdsh"):
            self.value["fanout"] = fanout
            argv = controller.command(self.config())
            self.assertIn("StrictHostKeyChecking=yes", argv)
            head = shlex.split(argv[-1])
            self.assertEqual(head[:2], ["bash", "-lc"])
            self.assertIn("fanout.sh", head[-1])
            self.assertIn("FANOUT_TOOL=" + fanout, head[-1])
            lexer = shlex.shlex(head[-1], posix=True, punctuation_chars=";")
            lexer.whitespace_split = True
            tokens = list(lexer)
            invocation = tokens[tokens.index("fanout"):]
            self.assertEqual(invocation[:2], ["fanout", "fixture-node"])
            node = shlex.split(invocation[-1])
            self.assertEqual(node[:2], ["bash", "-lc"])
            self.assertIn("sha256sum -c -", node[2])
            self.assertIn("--explain", node[2])
            self.assertIn("--test fixture-test", node[2])

    def test_transport_uncertainty_blocks_replay_after_restart(self):
        config = self.config()
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired("mock-ssh", 30)
        first = controller.cycle(config, timeout)
        self.assertEqual(first["status"], "uncertain")
        def must_not_run(*args, **kwargs):
            self.fail("Uncertain invocation must not replay")
        with self.assertRaisesRegex(RuntimeError, "reconciliation"):
            controller.cycle(config, must_not_run)

    def test_private_receipts_do_not_claim_gpu_acceptance(self):
        def runner(*args, **kwargs):
            return confirmed_result(args[0])
        receipt = controller.cycle(self.config(), runner)
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["workload_acceptance"], "not established by transport exit")
        self.assertTrue((Path(receipt["logs_directory"]) / "stdout.txt").read_bytes().startswith(b"fixture preview\n"))

    def test_successful_execution_is_not_repeated_by_next_timer_tick(self):
        self.value.update(mode="execute", execute_authorized=True)
        config = self.config()
        def runner(*args, **kwargs):
            return confirmed_result(args[0], b"fixture invocation")
        self.assertEqual(controller.cycle(config, runner)["status"], "completed")
        with self.assertRaisesRegex(RuntimeError, "already invoked"):
            controller.cycle(config, lambda *a, **k: self.fail("Timer replayed an executed scope"))

    def test_zero_fanout_exit_without_node_confirmation_is_uncertain(self):
        result = controller.cycle(self.config(), lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, b"node unreachable", b""))
        self.assertEqual(result["status"], "uncertain")

    def test_cross_process_invocation_guard(self):
        context = multiprocessing.get_context("spawn")
        ready, release = context.Event(), context.Event()
        config = self.config()
        process = context.Process(target=holding_cycle, args=(config, ready, release))
        process.start()
        try:
            self.assertTrue(ready.wait(10), "Worker did not acquire the invocation")
            with self.assertRaisesRegex(RuntimeError, "reconciliation"):
                controller.cycle(config, lambda *a, **k: self.fail("Concurrent invocation started"))
        finally:
            release.set()
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join()
        self.assertEqual(process.exitcode, 0)

    def test_task_is_disabled_and_registration_is_external(self):
        self.config()
        target = self.directory / "task.xml"
        result = controller.render_task(self.path, str(Path(sys.executable).resolve()), target)
        self.assertFalse(result["registered"])
        root = ET.parse(target).getroot()
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(root.find("t:Settings/t:Enabled", ns).text, "false")
        self.assertEqual(root.find("t:Settings/t:MultipleInstancesPolicy", ns).text, "IgnoreNew")


class NativeExemplar(unittest.TestCase):
    def test_derived_helper_preserves_upstream_config_gates_and_local_integrity(self):
        spec = importlib.util.spec_from_file_location("exemplar_builder", ROOT / "windows/exemplar/build_helper.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "derived"
            provenance = builder.build(output)
            spec = importlib.util.spec_from_file_location("native_exemplar_prepare", output / "prepare.py")
            native = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(native)
            spec = importlib.util.spec_from_file_location("upstream_exemplar_tests", ROOT / "components/nvisova-exemplar_recipe/source/tests/test_prepare.py")
            upstream = importlib.util.module_from_spec(spec)
            previous = sys.modules.get("prepare")
            sys.modules["prepare"] = native
            try:
                spec.loader.exec_module(upstream)
            finally:
                if previous is None:
                    del sys.modules["prepare"]
                else:
                    sys.modules["prepare"] = previous
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(upstream.ConfigTests)
            result = unittest.TestResult()
            suite.run(result)
            self.assertEqual(result.testsRun, 8)
            self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
            self.assertNotEqual(provenance["source_sha256"], provenance["output_sha256"])
            payload = Path(directory) / "payload"
            payload.mkdir()
            file = payload / "fixture.txt"
            file.write_text("reviewed payload")
            manifest = {"schema_version": 1, "files": native.inventory(payload)}
            self.assertEqual(native.verify(payload, manifest)["status"], "INTEGRITY_VERIFIED")
            file.write_text("tampered")
            with self.assertRaises(ValueError):
                native.verify(payload, manifest)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    raise SystemExit(not result.wasSuccessful())
