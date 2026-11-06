#!/usr/bin/env python3
"""Run standard-library tests and retain GitLab-compatible JUnit evidence."""

import sys
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


class Result(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        self.started = time.monotonic()
        self.current = ET.SubElement(self.report, "testcase", name=test.id())

    def stopTest(self, test):
        self.current.set("time", f"{time.monotonic() - self.started:.6f}")
        super().stopTest(test)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        ET.SubElement(self.current, "failure").text = self._exc_info_to_string(err, test)

    def addError(self, test, err):
        super().addError(test, err)
        ET.SubElement(self.current, "error").text = self._exc_info_to_string(err, test)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        ET.SubElement(self.current, "skipped", message=reason)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            ET.SubElement(self.current, "failure", message=str(subtest)).text = self._exc_info_to_string(err, test)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.report = ET.Element("testsuite", name="portable-preparation-boundaries")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    suite = unittest.defaultTestLoader.discover(str(root / "tests"))
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    result.report.set("tests", str(result.testsRun))
    result.report.set("failures", str(len(result.failures)))
    result.report.set("errors", str(len(result.errors)))
    ET.ElementTree(result.report).write(root / "test-results.xml", encoding="utf-8", xml_declaration=True)
    sys.exit(not result.wasSuccessful())
