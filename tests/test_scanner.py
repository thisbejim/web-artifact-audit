from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Union

from web_artifact_audit import ScanOptions, scan


class ScannerTests(unittest.TestCase):
    def make_site(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary = tempfile.TemporaryDirectory()
        return temporary, Path(temporary.name)

    def write(self, root: Path, name: str, content: Union[str, bytes]) -> None:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")

    def test_html_css_and_srcset_references_pass(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(
            root,
            "index.html",
            """<!doctype html>
<link rel="stylesheet" href="css/site.css">
<script type="module" src="js/app.js"></script>
<img src="img/logo.svg" srcset="img/logo.svg 1x, img/logo@2x.svg 2x">
""",
        )
        self.write(root, "css/site.css", "body { background: url('../img/logo.svg'); }")
        self.write(root, "js/app.js", 'new URL("../img/logo.svg", import.meta.url);')
        self.write(root, "img/logo.svg", "<svg></svg>")
        self.write(root, "img/logo@2x.svg", "<svg></svg>")
        result = scan(root)
        self.assertTrue(result.passed, result.findings)
        self.assertEqual(result.summary()["references"], 7)

    def test_data_url_in_srcset_does_not_create_fake_missing_file(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "index.html", '<img srcset="data:image/svg+xml,%3Csvg%3E 1x, logo.svg 2x">')
        self.write(root, "logo.svg", "<svg></svg>")
        result = scan(root)
        self.assertTrue(result.passed, result.findings)

    def test_missing_reference_has_actionable_location(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "index.html", '<script src="assets/app-123.js"></script>')
        result = scan(root)
        self.assertFalse(result.passed)
        self.assertEqual(result.errors[0].code, "WAA001")
        self.assertEqual(result.errors[0].file, "index.html")
        self.assertEqual(result.errors[0].line, 1)
        self.assertIn("assets/app-123.js", result.errors[0].message)

    def test_case_mismatch_is_not_hidden_by_macos(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "index.html", '<img src="Images/Logo.svg">')
        self.write(root, "images/logo.svg", "ok")
        result = scan(root)
        self.assertFalse(result.passed)
        self.assertEqual(result.errors[0].code, "WAA002")

    def test_base_path_flags_root_relative_urls(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "index.html", '<script src="/assets/app.js"></script>')
        self.write(root, "assets/app.js", "console.log('ok')")
        result = scan(root, ScanOptions(base_path="/docs/"))
        self.assertFalse(result.passed)
        self.assertEqual(result.errors[0].code, "WAA004")

    def test_parent_traversal_is_error(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "nested/index.html", '<script src="../../secret.js"></script>')
        result = scan(root)
        self.assertFalse(result.passed)
        self.assertEqual(result.errors[0].code, "WAA005")

    def test_sri_uses_strongest_algorithm(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        content = b"console.log('ok');\n"
        digest = base64.b64encode(hashlib.sha384(content).digest()).decode("ascii")
        self.write(root, "app.js", content)
        self.write(root, "index.html", f'<script src="app.js" integrity="sha256-bad sha384-{digest}"></script>')
        result = scan(root)
        self.assertTrue(result.passed, result.findings)

    def test_sri_mismatch_fails(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "app.js", "actual")
        self.write(root, "index.html", '<script src="app.js" integrity="sha256-ZmFrZQ=="></script>')
        result = scan(root)
        self.assertFalse(result.passed)
        self.assertEqual(result.errors[0].code, "WAA003")

    def test_manifest_icons_and_start_url_are_checked(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "index.html", '<link rel="manifest" href="manifest.webmanifest">')
        self.write(
            root,
            "manifest.webmanifest",
            json.dumps({"start_url": "./index.html", "icons": [{"src": "icons/icon.svg"}]}),
        )
        self.write(root, "icons/icon.svg", "<svg></svg>")
        self.write(root, "index.html", '<link rel="manifest" href="manifest.webmanifest">')
        result = scan(root)
        self.assertTrue(result.passed, result.findings)
        self.assertGreaterEqual(result.summary()["references"], 3)

    def test_manifest_missing_icon_is_reported_once(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "index.html", '<link rel="manifest" href="manifest.webmanifest">')
        self.write(root, "manifest.webmanifest", json.dumps({"icons": [{"src": "icons/missing.svg"}]}))
        result = scan(root)
        self.assertEqual([finding.code for finding in result.errors], ["WAA001"])

    def test_unlinked_invalid_web_manifest_is_reported(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "manifest.webmanifest", "{not json")
        result = scan(root)
        self.assertEqual([finding.code for finding in result.errors], ["WAA014"])

    def test_invalid_source_map_is_reported(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "app.js", "//# sourceMappingURL=app.js.map\n")
        self.write(root, "app.js.map", "not json")
        result = scan(root)
        self.assertFalse(result.passed)
        self.assertEqual(result.errors[0].code, "WAA013")

    def test_invalid_referenced_source_map_is_reported_once(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "app.js", "//# sourceMappingURL=app.js.map\n")
        self.write(root, "app.js.map", "not json")
        result = scan(root)
        self.assertEqual([finding.code for finding in result.errors], ["WAA013"])

    def test_html_base_href_can_model_deployment_prefix(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "index.html", '<base href="/docs/"><script src="assets/app.js"></script>')
        self.write(root, "assets/app.js", "ok")
        result = scan(root, ScanOptions(base_path="/docs/"))
        self.assertTrue(result.passed, result.findings)

    def test_dynamic_import_is_warning_or_strict_error(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "app.js", "import(name);\n")
        warning_result = scan(root)
        self.assertTrue(warning_result.passed)
        self.assertEqual(warning_result.warnings[0].code, "WAA006")
        strict_result = scan(root, ScanOptions(strict=True))
        self.assertFalse(strict_result.passed)
        self.assertEqual(strict_result.errors[0].code, "WAA006")

    def test_bare_module_specifier_is_not_treated_as_artifact_file(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "app.js", 'import React from "react";\n')
        result = scan(root)
        self.assertTrue(result.passed, result.findings)

    def test_import_map_local_targets_are_checked(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "index.html", '<script type="importmap" src="importmap.json"></script>')
        self.write(root, "importmap.json", json.dumps({"imports": {"app": "./assets/app.js"}}))
        self.write(root, "assets/app.js", "ok")
        result = scan(root)
        self.assertTrue(result.passed, result.findings)

    def test_workbox_precache_literals_are_checked(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "sw.js", 'precacheAndRoute([{url: "./index.html"}, {url: "./missing.css"}]);')
        self.write(root, "index.html", "ok")
        result = scan(root)
        self.assertFalse(result.passed)
        self.assertEqual([finding.code for finding in result.errors], ["WAA001"])

    def test_asset_manifest_paths_are_checked(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "asset-manifest.json", json.dumps({"files": {"main.js": "static/js/main.js", "missing": "static/js/missing.js"}}))
        self.write(root, "static/js/main.js", "ok")
        result = scan(root)
        self.assertFalse(result.passed)
        self.assertEqual([finding.code for finding in result.errors], ["WAA001"])

    def test_svg_embedded_reference_is_checked(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "icon.svg", '<svg><image href="missing.png" /></svg>')
        result = scan(root)
        self.assertFalse(result.passed)
        self.assertEqual(result.errors[0].code, "WAA001")

    def test_json_output_is_deterministic_shape(self) -> None:
        temporary, root = self.make_site()
        self.addCleanup(temporary.cleanup)
        self.write(root, "index.html", "<p>hello</p>")
        result = scan(root)
        payload = result.summary()
        self.assertEqual(payload["files"], 1)
        self.assertEqual(payload["references"], 0)


if __name__ == "__main__":
    unittest.main()
