import tempfile
import unittest
from pathlib import Path

from redfish_reachability_exporter import Collector, load_targets


class ExporterTests(unittest.TestCase):
    def test_load_targets_and_bounded_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.csv"
            path.write_text("node,su,address\nn1,SU1,192.0.2.1\nn2,SU2,192.0.2.2\n")
            targets = load_targets(path)
        collector = Collector(targets, interval=1800, timeout=1, concurrency=1)
        text = collector.render()
        self.assertIn('nvis_redfish_reachability_targets{cluster="IREN_MKZ",su="SU1"} 1', text)
        self.assertIn('nvis_redfish_credential_configured{cluster="IREN_MKZ"} 0', text)
        self.assertNotIn("192.0.2.1", text)
        self.assertNotIn('node="', text)

    def test_rejects_bad_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.csv"
            path.write_text("host,address\nn1,192.0.2.1\n")
            with self.assertRaises(ValueError):
                load_targets(path)


if __name__ == "__main__":
    unittest.main()
