import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from prepare import inventory, validate_config, verify


def config():
    return {
        "schema_version": 1, "cluster_alias": "benchmark", "network_mode": "airgap",
        "upstream": {"repository": "https://github.com/NVIDIA/exemplar-performance.git",
                     "commit": "a" * 40, "release": "approved"},
        "hardware": {"architecture": "x86_64", "gpu_type": "supported-gpu",
                     "gpus_per_node": 4, "nodes": ["compute-a", "compute-b"],
                     "transport": "roce", "expected_hcas_per_node": 2,
                     "socket_interface": "eth0", "transport_environment": {}},
        "scheduler": {"type": "slurm", "account": "benchmark", "partition": "gpu",
                      "qos": "", "operator_user": "operator"},
        "storage": {"layout": "node-local", "source_root": "/opt/recipe-source",
                    "install_root": "/opt/recipe-install", "image_root": "/opt/recipe-images",
                    "hf_cache": "/opt/model-cache", "evidence_root": "/var/lib/recipe-evidence"},
        "credentials": {"hf_token_file": "/secure/model-access", "ngc_credentials_file": "/secure/registry-access"},
        "workloads": [{"name": "supported-workload", "model_size": "size", "dtype": "bf16",
                       "scale": 8, "repeats": 1, "purpose": "diagnostic"}],
    }


class ConfigTests(unittest.TestCase):
    def test_valid_inputs_do_not_claim_readiness(self):
        result = validate_config(config())
        self.assertEqual(result["status"], "INPUTS_VALID")
        self.assertEqual(result["qualification"], "not assessed")

    def test_architecture_and_transport_are_configurable(self):
        data = config()
        data["hardware"]["architecture"] = "aarch64"
        data["hardware"]["transport"] = "efa"
        self.assertEqual(validate_config(data)["status"], "INPUTS_VALID")

    def test_unknown_or_malformed_inputs_rejected(self):
        with self.assertRaisesRegex(ValueError, "mapping"):
            validate_config([])
        data = config()
        data["password"] = "unexpected-field"
        with self.assertRaisesRegex(ValueError, "fields differ"):
            validate_config(data)
        data = config()
        data["hardware"]["nodes"] = [{}]
        with self.assertRaisesRegex(ValueError, "hostname"):
            validate_config(data)

    def test_template_cannot_launch(self):
        p = Path(__file__).resolve().parents[1] / "config/cluster.example.json"
        with self.assertRaisesRegex(ValueError, "placeholder"):
            validate_config(json.loads(p.read_text()))

    def test_scale_and_duplicate_nodes_rejected(self):
        for scale in (0, 3, 12, True):
            data = config()
            data["workloads"][0]["scale"] = scale
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                validate_config(data)
        data = config()
        data["hardware"]["nodes"] = ["compute-a", "compute-a"]
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_config(data)

    def test_unpinned_source_and_unsupported_scheduler(self):
        data = config()
        data["upstream"]["commit"] = "main"
        with self.assertRaisesRegex(ValueError, "immutable"):
            validate_config(data)
        data = config()
        data["scheduler"]["type"] = "other"
        with self.assertRaisesRegex(ValueError, "adapter"):
            validate_config(data)

    def test_rdma_requires_inventory(self):
        data = config()
        data["hardware"]["expected_hcas_per_node"] = 0
        with self.assertRaisesRegex(ValueError, "HCA"):
            validate_config(data)

    def test_secret_values_and_environment_rejected(self):
        data = config()
        data["credentials"]["hf_token_file"] = "hf_" + "A" * 30
        with self.assertRaisesRegex(ValueError, "credential-like"):
            validate_config(data)
        data = config()
        data["hardware"]["transport_environment"]["HF_TOKEN"] = "value"
        with self.assertRaisesRegex(ValueError, "credentials"):
            validate_config(data)
        data = config()
        data["credentials"]["token_value"] = "hidden"
        with self.assertRaisesRegex(ValueError, "references only"):
            validate_config(data)


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "payload"
        self.root.mkdir()
        (self.root / "source.txt").write_text("reviewed source\n")

    def manifest(self):
        return {"schema_version": 1, "files": inventory(self.root)}

    def test_round_trip_and_modified_file(self):
        m = self.manifest()
        self.assertEqual(verify(self.root, m)["status"], "INTEGRITY_VERIFIED")
        (self.root / "source.txt").write_text("changed source\n")
        with self.assertRaisesRegex(ValueError, "differs"):
            verify(self.root, m)

    def test_added_missing_and_mode_changed(self):
        m = self.manifest()
        extra = self.root / "extra.txt"
        extra.write_text("unexpected")
        with self.assertRaises(ValueError):
            verify(self.root, m)
        extra.unlink()
        source = self.root / "source.txt"
        source.chmod(0o755)
        with self.assertRaises(ValueError):
            verify(self.root, m)
        source.unlink()
        with self.assertRaises(ValueError):
            verify(self.root, m)

    def test_safe_cache_link_and_external_link(self):
        (self.root / "cache").mkdir()
        (self.root / "cache/model-config").symlink_to("../source.txt")
        m = self.manifest()
        self.assertEqual(verify(self.root, m)["files"], 2)
        (self.base / "private.txt").write_text("external")
        (self.root / "outside").symlink_to("../private.txt")
        with self.assertRaisesRegex(ValueError, "external symlink"):
            inventory(self.root)

    def test_credentials_directory_and_token_pattern(self):
        token = self.root / "token"
        token.write_text("secret")
        with self.assertRaisesRegex(ValueError, "credential"):
            inventory(self.root)
        token.unlink()
        (self.root / "source.txt").write_text("hf_" + "A" * 30)
        with self.assertRaisesRegex(ValueError, "credential pattern"):
            inventory(self.root)

    def test_manifest_traversal_and_duplicates(self):
        m = self.manifest()
        m["files"][0]["path"] = "../outside"
        with self.assertRaisesRegex(ValueError, "unsafe"):
            verify(self.root, m)
        m = self.manifest()
        m["files"].append(copy.deepcopy(m["files"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            verify(self.root, m)


if __name__ == "__main__":
    unittest.main()
