"""Installed package resources and configurable local application data."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
RESOURCE_ROOT = PACKAGE_ROOT / "resources"
LEGACY_ROOT = RESOURCE_ROOT / "legacy"
