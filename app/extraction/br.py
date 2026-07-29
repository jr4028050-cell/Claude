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
_ADDRESS_RE = re.compile(
    r"(?:Business Address|經營地址|Address\s*/\s*地址|Registered Address|"
    r"business address of the person\(s\)[^\n]*)\s*[:.]?\s*\n?"
    r"([^\n]+(?:\n(?!\s*(?:Nature of Business|Date of|New Registration|"
    r"Certificate|業務性質|發證日期|Address|地址|Effective Date|Particulars))"
    r"[^\n]+){0,5})",
    re.IGNORECASE,
)
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

    addr_m = _ADDRESS_RE.search(text)
    address = collapse_line(addr_m.group(1)) if addr_m else ""

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
