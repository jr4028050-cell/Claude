"""Coordinate-based extraction for NNC1/NAR1's own "Proposed Address of
the Company's Registered Office in Hong Kong" section (NNC1 第3節).

Same structural problem as the PI-NNC1 director page (see `pi_nnc1.py`'s
module docstring for the general rationale) and the same fix: this
section is also five labelled boxes (Flat/Floor/Block, Building, Street,
District, Country/Region) on a fixed Companies Registry template, and a
blank one has nowhere to fall through to but the neighbouring label or
the "「轉交」地址及郵政信箱號碼不獲接納" instructional note printed just
above the fields -- which is exactly what the flattened-text-stream
version captured on a real filing. Reuses the label-anchor + coordinate-
crop primitives from `coord_text.py`; only the section heading, the
field label vocabulary, and the calibrated fallback ratios differ from
`pi_nnc1.py` (this section's English labels turned out to be shorter —
plain "Region", not "Country／Region" — so its own keyword list is kept
separate rather than shared).
"""
from __future__ import annotations

import io
import re

from . import person_fields
from .coord_text import crop_value, find_word_any

_SECTION_RE = re.compile(r"Registered\s*Office|註冊辦事處", re.IGNORECASE)
_NOTE_RE = re.compile(r"acceptable|接納", re.IGNORECASE)

# 210, not pi_nnc1.py's 198: this section's "Street／Estate／Lot／Village"
# English restatement has a separate "etc." token starting at ~192.5,
# close enough to 198 that pdfplumber's crop clips it character-by-
# character rather than excluding the whole word ("etc." -> "tc.").
_ADDRESS_X0 = 210.0
_ADDRESS_RIGHT_MARGIN = 15.0
_WINDOW_ABOVE_PT = 24.0
_WINDOW_BELOW_PT = 14.0

# (result key, primary anchor keyword, fallback keywords)
_FIELD_SEQUENCE = (
    ("flat", "Block", ("Flat", "室")),
    ("building", "Building", ("大廈", "大度")),
    ("street", "Street", ("街道",)),
    ("district", "District", ("地區", "區")),
    ("country", "Region", ("地區", "國家", "Country", "囫家")),
)

# Last-resort fallback, expressed as a fraction of page height -- see
# pi_nnc1.py's own _RATIO_FALLBACK for why. Calibrated against one real
# filing (Nexcloud Technology Limited); narrower evidence base than
# pi_nnc1.py's two, so treat as a rough safety net, not a tight fit.
_RATIO_FALLBACK = {
    "flat": 0.606,
    "building": 0.648,
    "street": 0.687,
    "district": 0.728,
    "country": 0.768,
}


def find_registered_office_page(pdf):
    """The page carrying the "Proposed Address of the Company's
    Registered Office" section, or None if not found (e.g. a document
    type that doesn't carry this section at all)."""
    for page in pdf.pages:
        text = page.extract_text() or ""
        if _SECTION_RE.search(text):
            return page
    return None


def extract_registered_office_address(page) -> str:
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
    words.sort(key=lambda w: (w["top"], w["x0"]))
    address_x1 = page.width - _ADDRESS_RIGHT_MARGIN

    heading = find_word_any(words, ("Registered", "註冊辦事處"), 0.0)
    floor = heading["bottom"] if heading else 0.0
    note = find_word_any(words, ("acceptable", "接納"), floor)
    floor = note["bottom"] if note else max(floor, page.height * 0.55)

    raw: dict[str, str] = {}
    for key, primary, alts in _FIELD_SEQUENCE:
        anchor = find_word_any(words, (primary, *alts), floor)
        if anchor is not None:
            value = crop_value(
                page, anchor["top"], floor, _ADDRESS_X0, address_x1,
                _WINDOW_ABOVE_PT, _WINDOW_BELOW_PT,
            )
            floor = anchor["bottom"]
        else:
            ratio_top = page.height * _RATIO_FALLBACK[key]
            value = crop_value(
                page, ratio_top, floor, _ADDRESS_X0, address_x1,
                _WINDOW_ABOVE_PT, _WINDOW_BELOW_PT,
            )
            floor = max(floor, ratio_top)
        raw[key] = value

    return person_fields.assemble_address(
        raw["flat"], raw["building"], raw["street"], raw["district"], raw["country"]
    )


def extract_registered_office_from_pdf(pdf_bytes: bytes) -> str:
    """Empty string (never raises) if the document has no recognisable
    registered-office section, so callers can fall back to the legacy
    text-block regex parser."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = find_registered_office_page(pdf)
        if page is None:
            return ""
        return extract_registered_office_address(page)
