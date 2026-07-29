"""Shared field/status types for extraction results.

Every output field is a small object carrying not just the value but where it
came from and how confident we are in it, per PRD 第 6 节. The frontend uses
`status` to pick a badge colour and `source` to show provenance.
"""
from __future__ import annotations

from typing import Any, Optional

STATUS_EXTRACTED = "extracted"
STATUS_DEFAULT = "default"
STATUS_INFERRED = "inferred"
STATUS_MASKED = "masked"
STATUS_MISSING = "missing"


def field(
    value: str = "",
    source: str = "",
    status: str = STATUS_MISSING,
    raw: Optional[str] = None,
) -> dict[str, Any]:
    out = {"value": value or "", "source": source or "", "status": status}
    if raw:
        out["raw"] = raw
    return out


def extracted(value: str, source: str, raw: Optional[str] = None) -> dict[str, Any]:
    if not value:
        return missing()
    return field(value, source, STATUS_EXTRACTED, raw)


def default(value: str, source: str = "rule") -> dict[str, Any]:
    return field(value, source, STATUS_DEFAULT)


def inferred(value: str, source: str) -> dict[str, Any]:
    if not value:
        return missing()
    return field(value, source, STATUS_INFERRED)


def masked(value: str, source: str, raw: Optional[str] = None) -> dict[str, Any]:
    return field(value, source, STATUS_MASKED, raw)


def missing() -> dict[str, Any]:
    return field("", "", STATUS_MISSING)
