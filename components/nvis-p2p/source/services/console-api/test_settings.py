import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("server.py")
SPEC = importlib.util.spec_from_file_location("nvis_console_api", MODULE_PATH)
assert SPEC and SPEC.loader
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class SettingsValidationTests(unittest.TestCase):
    def test_working_defaults_are_valid_and_match_runtime_templates(self):
        settings = SERVER.normalize_settings(SERVER.DEFAULT_SETTINGS)
        self.assertEqual(settings["peer"]["download_bandwidth"], "50GB")
        self.assertEqual(settings["scheduler"], {"redis_pool_size": 1024, "redis_pool_timeout": "10s"})
        self.assertEqual(settings["service_policy"]["mode"], "uncapped")
        self.assertEqual(SERVER.settings_diff(settings)[1], [])

    def test_rejects_invalid_limits(self):
        settings = SERVER.deep_copy_default_settings()
        settings["peer"]["concurrent_pieces"] = 0
        with self.assertRaisesRegex(ValueError, "between 1 and 256"):
            SERVER.normalize_settings(settings)

        settings = SERVER.deep_copy_default_settings()
        settings["scheduler"]["redis_pool_timeout"] = "forever"
        with self.assertRaisesRegex(ValueError, "duration"):
            SERVER.normalize_settings(settings)

    def test_explicit_policy_renders_only_peer_unit_limits(self):
        settings = SERVER.deep_copy_default_settings()
        settings["service_policy"] = {
            "mode": "explicit",
            "cpu_quota_percent": 800,
            "memory_max": "16G",
            "nice": 0,
            "io_scheduling_class": "best-effort",
            "io_scheduling_priority": 4,
        }
        normalized = SERVER.normalize_settings(settings)
        rendered = SERVER.render_settings(normalized)
        unit = rendered[SERVER.PEER_UNIT]
        self.assertIn("CPUQuota=800%", unit)
        self.assertIn("MemoryMax=16G", unit)
        self.assertIn("IOSchedulingClass=best-effort", unit)
        self.assertNotIn("CPUQuota=800%", rendered[SERVER.SCHEDULER_CONFIG])

    def test_peer_and_redis_values_render_exactly_once(self):
        settings = SERVER.deep_copy_default_settings()
        settings["peer"].update({
            "download_bandwidth": "40GB",
            "upload_bandwidth": "30GB",
            "back_to_source_bandwidth": "20GB",
            "concurrent_pieces": 24,
        })
        settings["scheduler"].update({"redis_pool_size": 2048, "redis_pool_timeout": "20s"})
        rendered = SERVER.render_settings(SERVER.normalize_settings(settings))
        peer = rendered[SERVER.PEER_TEMPLATE]
        scheduler = rendered[SERVER.SCHEDULER_CONFIG]
        self.assertIn("  bandwidthLimit: 40GB", peer)
        self.assertIn("  bandwidthLimit: 30GB", peer)
        self.assertIn("  backToSourceBandwidthLimit: 20GB", peer)
        self.assertIn("  concurrentPieceCount: 24", peer)
        self.assertIn("    poolSize: 2048", scheduler)
        self.assertIn("    poolTimeout: 20s", scheduler)


if __name__ == "__main__":
    unittest.main()
