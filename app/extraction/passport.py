"""Passport extraction, sourced from the Machine-Readable Zone (MRZ)
rather than the visual data zone.

Per PRD 第 10.1 条: NNC1/PI-NNC1 carry no gender or date-of-birth field
at all, and a director's HKID/passport number is often masked or absent
outside the PI-NNC1 page. A passport upload is the authoritative source
for all three when provided.

A passport bio-data page is a photograph, not a document with a text
layer, so this always goes through OCR — and unlike a scanned CI/BR, the
visual data zone (name/sex/DOB/etc. printed in the labelled boxes) sits
under a printed hologram/security pattern that Tesseract reads as
near-total noise regardless of PSM mode or DPI; that pattern doesn't
cover the MRZ strip. Real Ministry-of-Foreign-Affairs-issued PRC
passports and ICAO 9303 TD3-format passports generally follow the same
44-characters-per-line MRZ layout, which is fixed-width and
self-describing enough to parse positionally instead of needing label
matching. The MRZ is therefore treated as authoritative here; the
visual zone is not parsed at all (its OCR yield was, on the one real
sample calibrated against, unusable).

Locating the MRZ within the page image is itself the hard part — a
scanned/photographed passport's framing varies, so a single fixed crop
fraction only works for one specific photo's proportions. This scans a
handful of candidate horizontal bands across the lower half of the
image (where the MRZ always sits on a TD3 passport) and OCRs each until
two lines that look like MRZ rows (long, mostly `[A-Z0-9<]`, several
"<" filler characters) turn up.
"""
from __future__ import annotations

import re

from . import schema

# Candidate (top, bottom) crop fractions of the image height to search
# for the MRZ strip, in the order tried. Narrow bands first (less noise
# if they hit), widening as a fallback. Calibrated against one real PRC
# passport photo; the passport's own bio-page-plus-MRZ block sat at
# roughly 75-79% of the full scanned image's height in that sample, but
# framing varies across scans/photos, hence the spread of alternatives.
_MRZ_BAND_FRACTIONS = (
    (0.74, 0.80), (0.70, 0.77), (0.78, 0.85), (0.65, 0.73),
    (0.82, 0.90), (0.55, 0.65), (0.45, 0.58), (0.85, 0.97),
)

_MRZ_CHAR_RE = re.compile(r"^[A-Z0-9<]+$")
_MRZ_LINE1_RE = re.compile(r"^P.?([A-Z]{3})([A-Z]*)<+([A-Z]*)")


def _looks_like_mrz_line(line: str) -> bool:
    cleaned = re.sub(r"[^A-Z0-9<]", "", line.upper())
    if len(cleaned) < 28 or not _MRZ_CHAR_RE.match(cleaned):
        return False
    # Line 1 (name) is usually padded with a long run of "<" filler;
    # line 2 (numbers/dates) often isn't, when every field is filled in
    # -- so a line close to the full 44-char TD3 width is accepted on
    # length alone, and only a shorter line needs the "<" padding as
    # corroborating evidence that it's really an MRZ row and not some
    # other OCR noise that happened to be long and alphanumeric.
    return cleaned.count("<") >= 2 or len(cleaned) >= 38


def _find_mrz_lines(image) -> tuple[str, str] | None:
    import pytesseract

    w, h = image.size
    for top_frac, bottom_frac in _MRZ_BAND_FRACTIONS:
        crop = image.crop((0, int(h * top_frac), w, int(h * bottom_frac)))
        text = pytesseract.image_to_string(crop, lang="eng", config="--psm 6")
        candidates = [
            re.sub(r"[^A-Z0-9<]", "", line.upper())
            for line in text.splitlines()
            if _looks_like_mrz_line(line)
        ]
        if len(candidates) >= 2:
            return candidates[0], candidates[1]
    return None


def _mrz_date_to_iso(yymmdd: str, *, is_expiry: bool) -> str:
    """MRZ dates are YYMMDD with no century. Expiry dates are always in
    the future relative to issue, so treated as 20xx; birth dates use
    the usual "no reasonable future birth date" pivot."""
    if not re.match(r"^[0-9]{6}$", yymmdd):
        return ""
    yy, mm, dd = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return ""
    if is_expiry:
        year = 2000 + yy
    else:
        import datetime
        pivot = datetime.date.today().year % 100
        year = 2000 + yy if yy <= pivot else 1900 + yy
    return f"{year:04d}-{mm:02d}-{dd:02d}"


_COUNTRY_CODE_MAP = {
    "CHN": "China", "HKG": "Hong Kong", "MAC": "Macao",
    "USA": "United States", "GBR": "United Kingdom",
}


def _country_name(code: str) -> str:
    return _COUNTRY_CODE_MAP.get(code, code)


def parse_mrz(line1: str, line2: str) -> dict:
    """Pure parsing step, split out from image/OCR handling so it can be
    tested directly against known MRZ strings rather than relying on
    OCR of a synthetic image. `line1`/`line2` are the already-OCR'd (or,
    in a test, hand-written) 44-character TD3 MRZ rows."""
    line2 = line2.ljust(44, "<")[:44]

    m1 = _MRZ_LINE1_RE.match(line1)
    surname_en = m1.group(2) if m1 else ""
    given_en = m1.group(3).rstrip("<") if m1 else ""
    issuing_country_code = m1.group(1) if m1 else ""

    passport_number = line2[0:9].rstrip("<")
    nationality_code = line2[10:13].rstrip("<")
    dob = _mrz_date_to_iso(line2[13:19], is_expiry=False)
    sex_code = line2[20:21]
    expiry = _mrz_date_to_iso(line2[21:27], is_expiry=True)

    sex = {"M": "Male", "F": "Female"}.get(sex_code, "")
    issuing_country = _country_name(issuing_country_code or nationality_code)

    return {
        "surname_en": schema.extracted(surname_en, "Passport") if surname_en else schema.missing(),
        "given_en": schema.extracted(given_en, "Passport") if given_en else schema.missing(),
        "id_info": schema.extracted(passport_number, "Passport") if passport_number else schema.missing(),
        "id_issuing_country": (
            schema.extracted(issuing_country, "Passport") if issuing_country else schema.missing()
        ),
        "gender": schema.extracted(sex, "Passport") if sex else schema.missing(),
        "dob": schema.extracted(dob, "Passport") if dob else schema.missing(),
        "expiry_date": schema.extracted(expiry, "Passport") if expiry else schema.missing(),
    }


def extract_passport_from_image(image) -> dict:
    """One passport's fields from a bio-data page image. Every field is
    `schema.missing()` (never a guess) if the MRZ can't be located or
    doesn't parse — a passport photo is expected to sometimes just not
    OCR cleanly, and this is the field's own last-resort source, so
    there's nothing further to fall back to."""
    mrz = _find_mrz_lines(image)
    if mrz is None:
        return empty_passport_fields()
    return parse_mrz(*mrz)


def empty_passport_fields() -> dict:
    return {
        "surname_en": schema.missing(),
        "given_en": schema.missing(),
        "id_info": schema.missing(),
        "id_issuing_country": schema.missing(),
        "gender": schema.missing(),
        "dob": schema.missing(),
        "expiry_date": schema.missing(),
    }


def extract_passport_from_pdf(pdf_bytes: bytes) -> dict:
    """Renders each page of the uploaded passport PDF/scan and returns
    the first page whose MRZ parses (a passport upload is expected to be
    a single bio-data page, but scanning the whole booklet by mistake
    shouldn't crash the request)."""
    from pdf2image import convert_from_bytes

    from .pdf_text import OCR_DPI

    images = convert_from_bytes(pdf_bytes, dpi=OCR_DPI)
    for image in images:
        fields = extract_passport_from_image(image)
        if fields["id_info"]["value"]:
            return fields
    return empty_passport_fields()
