from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from . import __version__
from .models import Finding, ScanOptions, ScanResult
from .scanner import scan


def _format_text(result: ScanResult) -> str:
    status = "PASS" if result.passed else "FAIL"
    lines = [
        f"{status} web-artifact-audit — {len(result.errors)} errors, {len(result.warnings)} warnings",
        f"Scanned {len(result.files)} files ({result.bytes_scanned:,} bytes) and checked {len(result.references)} local references.",
    ]
    if result.external_references:
        lines.append(f"Skipped {result.external_references} external/data references (no network access).")
    for finding in result.findings:
        location = finding.file or "artifact"
        if finding.line is not None:
            location += f":{finding.line}"
            if finding.column is not None:
                location += f":{finding.column}"
        lines.append(f"{finding.severity.upper():7} {finding.code} {location} — {finding.message}")
        if finding.hint:
            lines.append(f"         hint: {finding.hint}")
    return "\n".join(lines)


def _format_json(result: ScanResult) -> str:
    return json.dumps(
        {
            "tool": "web-artifact-audit",
            "version": __version__,
            "summary": result.summary(),
            "findings": [finding.to_dict() for finding in result.findings],
            "references": [reference.to_dict() for reference in result.references],
        },
        indent=2,
        sort_keys=True,
    )


def _format_sarif(result: ScanResult) -> str:
    sarif_results: List[Dict[str, Any]] = []
    for finding in result.findings:
        item: Dict[str, Any] = {
            "ruleId": finding.code,
            "level": "error" if finding.severity == "error" else "warning" if finding.severity == "warning" else "note",
            "message": {"text": finding.message},
        }
        if finding.file:
            region: Dict[str, Any] = {}
            if finding.line is not None:
                region["startLine"] = finding.line
            if finding.column is not None:
                region["startColumn"] = finding.column
            item["locations"] = [{"physicalLocation": {"artifactLocation": {"uri": finding.file}, "region": region}}]
        sarif_results.append(item)
    return json.dumps(
        {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": "web-artifact-audit", "version": __version__}}, "results": sarif_results}],
        },
        indent=2,
        sort_keys=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web-artifact-audit",
        description="Preflight a static web build output without a server, browser, Docker, or network.",
    )
    parser.add_argument("path", nargs="?", default="dist", help="published artifact directory (default: dist)")
    parser.add_argument("--base-path", default="/", help="deployment path for a project site, e.g. /docs/")
    parser.add_argument("--format", choices=("text", "json", "sarif"), default="text", help="output format (default: text)")
    parser.add_argument("--strict", action="store_true", help="fail on statically unresolved dynamic imports")
    parser.add_argument("--ignore", action="append", default=[], metavar="GLOB", help="ignore artifact paths matching GLOB; repeatable")
    parser.add_argument("--no-sri", action="store_true", help="skip local Subresource Integrity hash verification")
    parser.add_argument("--no-case-check", action="store_true", help="skip case-mismatch checks (not recommended)")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    options = ScanOptions(
        base_path=args.base_path,
        strict=args.strict,
        check_sri=not args.no_sri,
        check_case=not args.no_case_check,
        ignore=args.ignore,
    )
    result = scan(args.path, options)
    if args.format == "json":
        print(_format_json(result))
    elif args.format == "sarif":
        print(_format_sarif(result))
    else:
        print(_format_text(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
