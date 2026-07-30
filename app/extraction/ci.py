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
    r"(?:Company\s*No\.?|C\.?R\.?\s*No\.?|Certificate\s*No\.?|Number|編號|编号)\s*[:.]?\s*"
    r"([0-9]{6,8})",
    re.IGNORECASE,
)
_CRN_FALLBACK_RE = re.compile(r"\b([0-9]{7,8})\b")

# Real HK e-Certificates print the company name in Title Case ("Nexcloud
# Technology Limited"), not all-caps -- both name patterns need
# IGNORECASE, not just the anchored one, or a scanned/OCR'd certificate's
# name never matches at all. "I hereby certify that" also tolerates a
# leading "|" since Tesseract commonly misreads a capital "I" as a pipe.
_NAME_ANCHORED_RE = re.compile(
    r"(?:[I|]\s*)?hereby\s*certif(?:y|ies)\s*that\s*\n*\s*"
    r"([A-Za-z0-9 .,&'\-]+(?:LIMITED|LTD\.?))",
    re.IGNORECASE,
)
_NAME_FALLBACK_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9 .,&'\-]{2,}(?:LIMITED|LTD\.?))",
    re.IGNORECASE,
)

# Label only -- the date itself is handed to normalize_date() rather than
# matched inline, since a scanned certificate's OCR reconstruction can
# split "3 June 2026" across lines, and normalize_date()'s own
# sub-patterns already tolerate that (they match on \s+, which spans
# newlines) far better than a hand-rolled one-shot date regex would. The
# "Issued"/"on" two-word label itself is also commonly printed on two
# separate lines with the date's own two halves running alongside each
# ("Issued   3 June\non   2026.") -- since the value ends up on the same
# row as each half of its own label rather than after it, "on" is left
# optional here (matching just "Issued" is enough to anchor) and the
# stray "on" that lands inside the following window gets stripped in
# extract_ci() before parsing.
_DATE_LABEL_RE = re.compile(
    r"(?:Issued\s*(?:on\b)?|Date of Incorporation|day of incorporation|this date of|"
    r"incorporated[^0-9]{0,80}?\bon\b|成立日期|注冊成立日期|簽發日期|签发日期)\s*[:.]?\s*",
    re.IGNORECASE,
)
# Strips a standalone "on" from the date window -- see _DATE_LABEL_RE.
_STRAY_ON_RE = re.compile(r"(?<!\S)on(?!\S)", re.IGNORECASE)


def extract_ci(text: str) -> dict:
    text = text or ""

    name_m = _NAME_ANCHORED_RE.search(text) or _NAME_FALLBACK_RE.search(text)
    name_en = collapse_line(name_m.group(1)) if name_m else ""

    crn_m = _CRN_ANCHORED_RE.search(text)
    crn = crn_m.group(1) if crn_m else ""
    if not crn:
        crn_m = _CRN_FALLBACK_RE.search(text)
        crn = crn_m.group(1) if crn_m else ""

    label_m = _DATE_LABEL_RE.search(text)
    if label_m:
        window = _STRAY_ON_RE.sub(" ", text[label_m.end():label_m.end() + 40])
        incorp_date, incorp_raw = normalize_date(window)
    else:
        incorp_date, incorp_raw = "", None

    return {
        "name_en": schema.extracted(name_en, "CI") if name_en else schema.missing(),
        "crn": schema.extracted(crn, "CI") if crn else schema.missing(),
        "incorp_date": (
            schema.extracted(incorp_date, "CI", raw=incorp_raw)
            if incorp_date
            else schema.missing()
        ),
    }
