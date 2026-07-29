"""Text/date/address normalization helpers used across the rule extractors."""
from __future__ import annotations

import re
from typing import Optional

from dateutil import parser as dateutil_parser

_CN_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTH_NAME_DATE_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{4})\b",
    re.IGNORECASE,
)


def clean_whitespace(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def collapse_line(text: Optional[str]) -> str:
    """Collapse to a single line/space-joined string, trimming punctuation noise."""
    if not text:
        return ""
    text = clean_whitespace(text).replace("\n", " ")
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" :,-　")


def normalize_date(raw: Optional[str]) -> tuple[str, Optional[str]]:
    """Return (iso_date, raw) or ("", raw) if unparseable. Never raises."""
    if not raw:
        return "", None
    raw_clean = clean_whitespace(raw)

    m = _ISO_DATE_RE.search(raw_clean)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", raw_clean

    m = _CN_DATE_RE.search(raw_clean)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}", raw_clean

    m = _MONTH_NAME_DATE_RE.search(raw_clean)
    if m:
        try:
            dt = dateutil_parser.parse(m.group(0), dayfirst=True, fuzzy=True)
            return dt.strftime("%Y-%m-%d"), raw_clean
        except (ValueError, OverflowError):
            pass

    m = _NUMERIC_DATE_RE.search(raw_clean)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}", raw_clean
        if 1 <= d <= 12 and 1 <= mo <= 31:
            # ambiguous MM/DD/YYYY input, fall back to swapping
            return f"{y:04d}-{d:02d}-{mo:02d}", raw_clean

    try:
        dt = dateutil_parser.parse(raw_clean, fuzzy=True, dayfirst=True)
        return dt.strftime("%Y-%m-%d"), raw_clean
    except (ValueError, OverflowError):
        return "", raw_clean


_HK_MARKERS = (
    "HONG KONG",
    "HONGKONG",
    "香港",
    "KOWLOON",
    "九龍",
    "九龙",
    "NEW TERRITORIES",
    "新界",
)


def guess_country_from_address(address: Optional[str]) -> str:
    if not address:
        return ""
    upper = address.upper()
    for marker in _HK_MARKERS:
        if marker.upper() in upper:
            return "Hong Kong"
    # fall back to the last comma-separated segment, title-cased
    parts = [p.strip() for p in re.split(r"[,\n]", address) if p.strip()]
    if parts:
        return parts[-1].title()
    return ""


def looks_masked(value: Optional[str]) -> bool:
    if not value:
        return False
    return "*" in value or "X" * 3 in value.upper()
