"""Offline static web build-artifact checks."""

from .models import Finding, ScanOptions, ScanResult
from .scanner import scan

__all__ = ["Finding", "ScanOptions", "ScanResult", "scan"]
__version__ = "0.1.0"
