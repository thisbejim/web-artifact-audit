"""Tiny dependency-free PEP 517 backend for this stdlib-only project.

Keeping the backend in-tree means ``pip install .`` works in an offline
environment without first downloading setuptools or another build system.
It intentionally implements only the wheel hooks this project needs.
"""

from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path
from typing import Dict, Optional


NAME = "web-artifact-audit"
MODULE = "web_artifact_audit"
VERSION = "0.1.0"
DIST_INFO = "web_artifact_audit-0.1.0.dist-info"


def _metadata_files() -> Dict[str, bytes]:
    metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: {NAME}\n"
        f"Version: {VERSION}\n"
        "Summary: Offline preflight checks for static web build artifacts\n"
        "Requires-Python: >=3.9\n"
        "License: MIT\n"
        "Author: James\n\n"
    ).encode("utf-8")
    wheel = (
        "Wheel-Version: 1.0\n"
        "Generator: web-artifact-audit-build-backend\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    ).encode("utf-8")
    entry_points = b"[console_scripts]\nweb-artifact-audit = web_artifact_audit.cli:main\n"
    return {
        f"{DIST_INFO}/METADATA": metadata,
        f"{DIST_INFO}/WHEEL": wheel,
        f"{DIST_INFO}/entry_points.txt": entry_points,
    }


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def prepare_metadata_for_build_wheel(metadata_directory: str, config_settings: Optional[dict] = None) -> str:
    destination = Path(metadata_directory) / DIST_INFO
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in _metadata_files().items():
        (Path(metadata_directory) / name).write_bytes(content)
    return DIST_INFO


def build_wheel(wheel_directory: str, config_settings: Optional[dict] = None, metadata_directory: Optional[str] = None) -> str:
    wheel_name = f"web_artifact_audit-{VERSION}-py3-none-any.whl"
    wheel_path = Path(wheel_directory) / wheel_name
    root = _project_root()
    members: Dict[str, bytes] = {}
    source = root / "src" / MODULE
    for path in sorted(source.rglob("*")):
        if path.is_file():
            members[f"{MODULE}/{path.relative_to(source).as_posix()}"] = path.read_bytes()
    members.update(_metadata_files())
    records = []
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            content = members[name]
            archive.writestr(name, content)
            digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode("ascii").rstrip("=")
            records.append(f"{name},sha256={digest},{len(content)}")
        records.append(f"{DIST_INFO}/RECORD,,")
        archive.writestr(f"{DIST_INFO}/RECORD", "\n".join(records) + "\n")
    return wheel_name
