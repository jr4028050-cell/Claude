"""BR (Business Registration Certificate) field extraction."""
from __future__ import annotations

import re

from . import schema
from .normalize import collapse_line, normalize_date

_TRADING_NAME_RE = re.compile(
    r"(?:Name of Business|Business Name|業務名稱|商業名稱)\s*[:.]?\s*\n?\s*([^\n]+)",
    re.IGNORECASE,
)
_BR_NUMBER_RE = re.compile(
    r"(?:Business Registration Number|BR\s*No\.?|登記證號碼)\s*[:.]?\s*"
    r"([0-9\-]{8,20})",
    re.IGNORECASE,
)
_ADDRESS_LABEL_STRONG = (
    r"(?:Business Address|經營地址|Registered Address|"
    # official Form 2 layout: 地址 / Address stacked on two lines (either order)
    r"地\s*址\s*/?\s*\n?\s*Address|Address\s*/?\s*\n?\s*地\s*址|"
    r"business address of the person\(s\)[^\n]*)"
)
_ADDRESS_STOP = (
    r"(?:Nature of Business|Date of|New Registration|Certificate|Status|"
    r"業務性質|法律地位|發證日期|生效日期|屆滿日期|登記證號碼|"
    r"Address|地址|Effective Date|Particulars)"
)
_ADDRESS_STRONG_RE = re.compile(
    _ADDRESS_LABEL_STRONG + r"\s*[:.]?\s*\n?"
    r"([^\n]+(?:\n(?!\s*" + _ADDRESS_STOP + r")[^\n]+){0,5})",
    re.IGNORECASE,
)
# Some real Form 2 extractions only surface the English half ("Address") as
# its own line, with the Chinese "地址" caption lost in text-layer/OCR
# extraction. Match it only when it is the *entire* line (nothing else on
# it) so running text that happens to contain the word "address" (e.g.
# footer notices about notifying the Registrar of an address change) is
# not mistaken for the field label.
_ADDRESS_BARE_LABEL_RE = re.compile(
    r"^[ \t]*(?:Address|地\s*址)[ \t]*:?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_ADDRESS_BARE_VALUE_RE = re.compile(
    r"\s*\n?([^\n]+(?:\n(?!\s*" + _ADDRESS_STOP + r")[^\n]+){0,5})",
    re.IGNORECASE,
)


def _extract_address(text: str) -> str:
    m = _ADDRESS_STRONG_RE.search(text)
    if m:
        return collapse_line(m.group(1))

    label_m = _ADDRESS_BARE_LABEL_RE.search(text)
    if not label_m:
        return ""
    value_m = _ADDRESS_BARE_VALUE_RE.match(text, label_m.end())
    return collapse_line(value_m.group(1)) if value_m else ""
_NATURE_RE = re.compile(
    r"(?:Nature of Business|業務性質)\s*[:.]?\s*\n?\s*([^\n]+)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"(?:Date of Commencement(?:\s*of Business)?|Effective Date|生效日期|開業日期)"
    r"\s*[:.]?\s*"
    r"([0-9]{1,2}[/\-. ][A-Za-z0-9]{1,9}[/\-. ][0-9]{4}|"
    r"[0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2}|"
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
    re.IGNORECASE,
)


def extract_br(text: str) -> dict:
    text = text or ""

    trading_m = _TRADING_NAME_RE.search(text)
    trading_name = collapse_line(trading_m.group(1)) if trading_m else ""

    number_m = _BR_NUMBER_RE.search(text)
    br_number = number_m.group(1).strip() if number_m else ""

    address = _extract_address(text)

    nature_m = _NATURE_RE.search(text)
    nature = collapse_line(nature_m.group(1)) if nature_m else ""

    date_m = _DATE_RE.search(text)
    effective_date, effective_raw = (
        normalize_date(date_m.group(1)) if date_m else ("", None)
    )

    return {
        "trading_name": (
            schema.extracted(trading_name, "BR") if trading_name else schema.missing()
        ),
        "br_number": (
            schema.extracted(br_number, "BR") if br_number else schema.missing()
        ),
        "business_address": (
            schema.extracted(address, "BR") if address else schema.missing()
        ),
        "nature_of_business": (
            schema.extracted(nature, "BR") if nature else schema.missing()
        ),
        "effective_date": (
            schema.extracted(effective_date, "BR", raw=effective_raw)
            if effective_date
            else schema.missing()
        ),
    }
