"""Reading Odoo manifests without running them, and comparing module names across versions."""

from __future__ import annotations

import ast
import re
from typing import Any

MANIFEST_FILES = ("__manifest__.py", "__openerp__.py")
MAX_MANIFEST_BYTES = 200_000

# Odoo's default when a manifest has no license key.
DEFAULT_LICENSE = "LGPL-3"
PROPRIETARY_LICENSES = {"OPL-1", "OEEL-1", "OTHER PROPRIETARY"}

_VERSION_WORDS = re.compile(r"\b(?:odoo\s*)?v?\d{1,2}(?:\.\d)?\b", re.IGNORECASE)
_NOT_WORD = re.compile(r"[^a-z0-9]+")
_ODOO_VERSION = re.compile(r"^(\d{1,2}\.\d)(?:\.\d+)*$")


def parse_manifest(text: str) -> dict[str, Any]:
    """Return the manifest's dict, keeping only values that are plain literals.

    Manifests found on GitHub are untrusted, so they are parsed, never executed.
    """
    if len(text) > MAX_MANIFEST_BYTES:
        return {}
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        result: dict[str, Any] = {}
        for key, value in zip(node.keys, node.values, strict=False):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            try:
                result[key.value] = ast.literal_eval(value)
            except (ValueError, TypeError, SyntaxError, RecursionError):
                continue
        return result
    return {}


def normalize_name(name: str) -> str:
    """'Odoo 18 HR Payroll' and 'Odoo 20 HR Payroll' both become 'hr payroll'."""
    without_versions = _VERSION_WORDS.sub(" ", name.lower())
    return " ".join(_NOT_WORD.sub(" ", without_versions).split())


def search_phrase(name: str) -> str:
    """The display name without its Odoo version, keeping the original casing for search."""
    stripped = _VERSION_WORDS.sub(" ", name)
    return " ".join(re.sub(r"[\"&|()]", " ", stripped).split())


def odoo_version(manifest_version: object) -> str:
    """'18.0.1.2.0' -> '18.0'; also used for branch names like '18.0'. Anything else -> ''."""
    match = _ODOO_VERSION.match(str(manifest_version or "").strip())
    if not match or not 8 <= int(match.group(1).split(".")[0]) <= 40:
        return ""  # '1.0.3' is the module's own version, not Odoo's
    return match.group(1)


def split_authors(author: object) -> set[str]:
    if not isinstance(author, str):
        return set()
    return {part.strip() for part in author.split(",") if part.strip()}


def normalize_website(url: str) -> str:
    url = url.lower().strip()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    return url.split("/")[0]


def is_proprietary(license_name: str) -> bool:
    return license_name.strip().upper() in PROPRIETARY_LICENSES
