"""Coordinate-based field extraction for the PI-NNC1 page.

PI-NNC1 ("First Company Secretary／Director (Natural Person) – Protected
Information", 指明編號 1/2023) is a fixed-position Companies Registry
template: one page per person, printed the same way in every filing. That
makes it a poor fit for the label-regex-over-flattened-text approach used
for the rest of this document type (`nnc1.py`) — a blank cell there has no
choice but to fall through to *some* nearby text, which on a fixed form
means the neighbouring label or an instructional note, not a missing-value
signal. Calibrated against two real filings (Anger Trading Co., Limited
and Ornaart Company Limited), this module instead crops each field's
value box out of the page by coordinate and never reads outside it.

Layout, established from both samples' `page.extract_words()` output:
every field is printed as [Chinese label + value, on one row] directly
above [the English restatement of the label alone, on the next row] — so
each field is found by locating its English label word on the page, then
cropping the row *above* it (where the value actually lives) within an
x-range that starts well to the right of every label in the section and
therefore can never capture label text, however it drifts vertically.
Both real samples confirm two further quirks worth calling out because
they'd otherwise look like extraction bugs:

- Some (but not all) Chinese label glyphs come out corrupted in certain
  PDF exports (大廈 -> 大度, 國家 -> 囫家 in the Anger Trading sample) and
  "Surname" itself can come out as "Sumame" (rn -> m). English anchors are
  therefore tried first; known-corrupted spellings are included as
  fallback alternates rather than trusted as primaries anywhere.
- "Full Number" is printed twice — once inside "Identity Card(Full
  Number)" next to the HKID cell, once for the passport number itself —
  so the passport-number search is floored below wherever the HKID
  anchor was found, the same sequential-floor technique used for every
  field here to keep each crop inside its own row band.
"""
from __future__ import annotations

import io
import re

from . import person_fields
from .coord_text import crop_value, find_word, find_word_any

_PAGE_HEADING_RE = re.compile(r"^\s*PI-NNC1")
_PROTECTED_INFO_RE = re.compile(r"Protected\s*Information|受保護資料", re.IGNORECASE)

# Vertical crop window, relative to the matched anchor word's own `top`:
# value rows sit anywhere from ~6 to ~16pt above the English-label anchor
# (or, when a fallback lands on the Chinese label instead, on very nearly
# the same row) with the label/value gap never exceeding these across
# either calibration sample -- generous on both sides on purpose, since
# the x-range restriction below is what actually keeps label text out.
_WINDOW_ABOVE_PT = 24.0
_WINDOW_BELOW_PT = 14.0

# Column x-ranges, in PDF points. Chosen from both samples' word boxes so
# the left edge sits well past the widest label in that section (max
# observed label x1 ~254pt in the identity block, ~194pt in the address
# block) and the right edge stays short of the HKID row's empty "( )"
# check-digit box (starts ~505pt) so it can never bleed into an adjacent
# field's crop.
_IDENTITY_X0 = 280.0
_IDENTITY_X1 = 495.0
_ADDRESS_X0 = 198.0
_ADDRESS_RIGHT_MARGIN = 15.0

# (result key, primary anchor keyword, fallback keywords, column)
# Order matters: each field's search starts at the previous field's
# anchor bottom, which is what keeps e.g. the passport section's "Full
# Number" from matching the HKID row's "Card(Full Number)" above it, and
# the address section's "Country" from matching "Issuing Country" above
# it, without needing every field to be individually scoped.
_FIELD_SEQUENCE = (
    ("chinese_name", "Chinese", ("中文姓名",), "identity"),
    ("surname_en", "English", ("Surname", "Sumame", "姓氏"), "identity"),
    ("given_en", "Other", ("Names", "名字"), "identity"),
    ("hkid_raw", "Identity", ("身分識別", "HKID", "香港身分證", "香港身份證"), "identity"),
    ("issuing_country", "Issuing", ("簽發國家",), "identity"),
    ("passport_number", "Full", ("完整號碼", "Number"), "identity"),
    ("flat", "Block", ("Flat", "室"), "address"),
    ("building", "Building", ("大廈", "大度"), "address"),
    ("street", "Street", ("街道",), "address"),
    ("district", "District", ("地區", "區"), "address"),
    ("country", "Country", ("國家", "囫家"), "address"),
)

# Last-resort fallback only: if *neither* the primary nor any alternate
# keyword can be found at all (e.g. a template revision with different
# wording), reposition using each field's anchor position averaged across
# both calibration samples, expressed as a fraction of page height so it
# still scales to a differently-sized page.
_RATIO_FALLBACK = {
    "chinese_name": 0.477,
    "surname_en": 0.510,
    "given_en": 0.543,
    "hkid_raw": 0.591,
    "issuing_country": 0.624,
    "passport_number": 0.660,
    "flat": 0.711,
    "building": 0.750,
    "street": 0.792,
    "district": 0.827,
    "country": 0.872,
}


def find_pi_nnc1_pages(pdf) -> list:
    """Every page whose text starts with the "PI-NNC1" page code and
    contains the bilingual "Protected Information / 受保護資料" heading —
    one such page per person's particulars, per PRD."""
    pages = []
    for page in pdf.pages:
        text = (page.extract_text() or "").strip()
        if _PAGE_HEADING_RE.match(text) and _PROTECTED_INFO_RE.search(text):
            pages.append(page)
    return pages


def _fix_comma_spacing(text: str) -> str:
    # Some PDF exports lay a comma and the next character with ~zero gap
    # between them ("2304,23/F"), which pdfplumber then reads as a single
    # merged word with no space to collapse -- restore the conventional
    # ", " an address value should read with. Address values only (never
    # applied to names/IDs), since it would mangle a comma-grouped number.
    return re.sub(r",(?=\S)", ", ", text)


def extract_pi_nnc1_person(page, source: str) -> dict:
    """Crop every PI-NNC1 field on `page` by coordinate and return the
    same `{"fields": {...}, ...}` shape `nnc1.py`'s legacy text-block
    parser produces, so callers don't need to know which path was used."""
    words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
    words.sort(key=lambda w: (w["top"], w["x0"]))

    identity_x1 = min(_IDENTITY_X1, page.width - 20.0)
    address_x1 = page.width - _ADDRESS_RIGHT_MARGIN
    col_bounds = {
        "identity": (_IDENTITY_X0, identity_x1),
        "address": (_ADDRESS_X0, address_x1),
    }

    # Floor the very first search below the page's own heading/company-
    # name/instructional-note text (which can otherwise false-match e.g.
    # "Chinese" inside "...OR Chinese Company Name" up in the header).
    protected = find_word(words, "Protected")
    floor = protected["bottom"] if protected else 0.0
    capacity = find_word(words, "Capacity", floor)
    floor = capacity["bottom"] if capacity else max(floor, page.height * 0.35)

    address_heading_seen = False
    raw: dict[str, str] = {}
    for key, primary, alts, column in _FIELD_SEQUENCE:
        if column == "address" and not address_heading_seen:
            # The "Usual Residential Address of Director" section heading
            # prints its English words (x0 up to ~342) well inside the
            # address value column (x0 >= _ADDRESS_X0) -- without floor-
            # ing past it first, the first address field's crop window
            # catches the tail of the heading itself ("...idential
            # Address of Director") ahead of the real Flat/Floor/Block
            # value.
            heading = find_word_any(words, ("Residential", "通常住址"), floor)
            floor = heading["bottom"] if heading else max(floor, page.height * 0.65)
            address_heading_seen = True

        x0, x1 = col_bounds[column]
        anchor = find_word_any(words, (primary, *alts), floor)
        if anchor is not None:
            value = crop_value(page, anchor["top"], floor, x0, x1, _WINDOW_ABOVE_PT, _WINDOW_BELOW_PT)
            floor = anchor["bottom"]
        else:
            ratio_top = page.height * _RATIO_FALLBACK[key]
            value = crop_value(page, ratio_top, floor, x0, x1, _WINDOW_ABOVE_PT, _WINDOW_BELOW_PT)
            floor = max(floor, ratio_top)
        if column == "address" and value:
            value = _fix_comma_spacing(value)
        raw[key] = value

    hkid = person_fields.clean_hkid_value(raw["hkid_raw"])
    residential_address = person_fields.assemble_address(
        raw["flat"], raw["building"], raw["street"], raw["district"], raw["country"]
    )

    return person_fields.build_person_fields(
        raw["surname_en"],
        raw["given_en"],
        raw["chinese_name"],
        residential_address,
        hkid,
        raw["passport_number"],
        raw["issuing_country"],
        source,
    )


def extract_directors_from_pdf(pdf_bytes: bytes, source: str) -> list[dict]:
    """One `fields` dict per PI-NNC1 page found in the PDF, in page
    order. Returns an empty list (never raises) for a PDF with no
    PI-NNC1 pages, so callers can fall back to the legacy text-block
    parser for scanned/OCR'd or non-standard documents."""
    import pdfplumber

    directors = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in find_pi_nnc1_pages(pdf):
            person = extract_pi_nnc1_person(page, source)
            directors.append(person["fields"])
    return directors
