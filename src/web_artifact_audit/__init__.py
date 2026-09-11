"""Offline static web build-artifact checks."""

from .models import AssetReference, Finding, ScanOptions, ScanResult
from .scanner import scan

__all__ = ["AssetReference", "Finding", "ScanOptions", "ScanResult", "scan"]
__version__ = "0.1.0"
