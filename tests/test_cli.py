from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from web_artifact_audit.cli import main


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(arguments))
        return code, output.getvalue()

    def test_json_report_is_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text('<img src="logo.svg">', encoding="utf-8")
            (root / "logo.svg").write_text("ok", encoding="utf-8")
            code, output = self.run_cli(str(root), "--format", "json")
        self.assertEqual(code, 0)
        report = json.loads(output)
        self.assertTrue(report["summary"]["passed"])
        self.assertEqual(report["tool"], "web-artifact-audit")

    def test_sarif_report_contains_source_location(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text('<script src="missing.js"></script>', encoding="utf-8")
            code, output = self.run_cli(str(root), "--format", "sarif")
        self.assertEqual(code, 1)
        report = json.loads(output)
        finding = report["runs"][0]["results"][0]
        self.assertEqual(finding["ruleId"], "WAA001")
        self.assertEqual(finding["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], "index.html")

    def test_missing_path_is_a_blocking_input_error(self) -> None:
        code, output = self.run_cli("/private/tmp/web-artifact-audit-path-that-does-not-exist")
        self.assertEqual(code, 1)
        self.assertIn("WAA100", output)


if __name__ == "__main__":
    unittest.main()
