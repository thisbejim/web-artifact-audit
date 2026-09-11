from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Finding:
    """A deterministic, source-located audit result."""

    code: str
    severity: str
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    reference: Optional[str] = None
    hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.file is not None:
            result["file"] = self.file
        if self.line is not None:
            result["line"] = self.line
        if self.column is not None:
            result["column"] = self.column
        if self.reference is not None:
            result["reference"] = self.reference
        if self.hint is not None:
            result["hint"] = self.hint
        return result


@dataclass(frozen=True)
class AssetReference:
    """A local URL-like reference discovered in an artifact."""

    file: str
    line: int
    column: int
    target: str
    kind: str
    source: str
    integrity: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "target": self.target,
            "kind": self.kind,
            "source": self.source,
        }
        if self.integrity:
            result["integrity"] = self.integrity
        return result


@dataclass
class ScanOptions:
    """User-configurable scan policy."""

    base_path: str = "/"
    strict: bool = False
    check_sri: bool = True
    check_case: bool = True
    ignore: List[str] = field(default_factory=list)

    def normalized_base_path(self) -> str:
        value = self.base_path.strip()
        if not value:
            return "/"
        if not value.startswith("/"):
            value = "/" + value
        value = "/" + "/".join(part for part in value.split("/") if part)
        return value if value == "/" else value + "/"


@dataclass
class ScanResult:
    """The complete output of one audit."""

    root: Path
    options: ScanOptions
    findings: List[Finding] = field(default_factory=list)
    references: List[AssetReference] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    bytes_scanned: int = 0
    external_references: int = 0

    @property
    def errors(self) -> List[Finding]:
        return [finding for finding in self.findings if finding.severity == "error"]

    @property
    def warnings(self) -> List[Finding]:
        return [finding for finding in self.findings if finding.severity == "warning"]

    @property
    def infos(self) -> List[Finding]:
        return [finding for finding in self.findings if finding.severity == "info"]

    @property
    def passed(self) -> bool:
        return not self.errors

    def sort_findings(self) -> None:
        self.findings.sort(
            key=lambda item: (
                SEVERITY_RANK.get(item.severity, 9),
                item.file or "",
                item.line or 0,
                item.column or 0,
                item.code,
            )
        )

    def summary(self) -> Dict[str, Any]:
        return {
            "root": str(self.root),
            "files": len(self.files),
            "bytes": self.bytes_scanned,
            "references": len(self.references),
            "external_references": self.external_references,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "infos": len(self.infos),
            "passed": self.passed,
            "base_path": self.options.normalized_base_path(),
        }
