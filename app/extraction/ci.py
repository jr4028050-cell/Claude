"""CI (Certificate of Incorporation) field extraction.

Anchors on the standard e-Certificate / paper Certificate of Incorporation
wording issued by the HK Companies Registry. Layouts vary across the years
(pre-2018 script certificates vs. current e-Certificates), so patterns are
kept permissive with a name/number/date fallback when no anchor matches.
"""
from __future__ import annotations

import re

from . import schema
from .normalize import clean_whitespace, collapse_line, normalize_date

_CRN_ANCHORED_RE = re.compile(
    r"(?:Company\s*No\.?|C\.?R\.?\s*No\.?|Certificate\s*No\.?|Number)\s*[:.]?\s*"
    r"([0-9]{6,8})",
    re.IGNORECASE,
)
_CRN_FALLBACK_RE = re.compile(r"\b([0-9]{7,8})\b")

_NAME_ANCHORED_RE = re.compile(
    r"(?:I hereby certify that|hereby certifies that)\s*\n*\s*"
    r"([A-Z0-9 .,&'\-]+(?:LIMITED|LTD\.?))",
    re.IGNORECASE,
)
_NAME_FALLBACK_RE = re.compile(
    r"([A-Z][A-Z0-9 .,&'\-]{2,}(?:LIMITED|LTD\.?))"
)

_DATE_ANCHORED_RE = re.compile(
    r"(?:Date of Incorporation|day of incorporation|this date of|"
    r"incorporated[^0-9]{0,80}?on|成立日期|注冊成立日期)\s*[:.]?\s*"
    r"([0-9]{1,2}[/\-. ][A-Za-z0-9]{1,9}[/\-. ][0-9]{4}|"
    r"[0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2}|"
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
    re.IGNORECASE | re.DOTALL,
)


def extract_ci(text: str) -> dict:
    text = text or ""

    name_m = _NAME_ANCHORED_RE.search(text) or _NAME_FALLBACK_RE.search(text)
    name_en = collapse_line(name_m.group(1)) if name_m else ""

    crn_m = _CRN_ANCHORED_RE.search(text)
    crn = crn_m.group(1) if crn_m else ""
    if not crn:
        crn_m = _CRN_FALLBACK_RE.search(text)
        crn = crn_m.group(1) if crn_m else ""

    date_m = _DATE_ANCHORED_RE.search(text)
    incorp_date, incorp_raw = normalize_date(date_m.group(1)) if date_m else ("", None)

    return {
        "name_en": schema.extracted(name_en, "CI") if name_en else schema.missing(),
        "crn": schema.extracted(crn, "CI") if crn else schema.missing(),
        "incorp_date": (
            schema.extracted(incorp_date, "CI", raw=incorp_raw)
            if incorp_date
            else schema.missing()
        ),
    }
