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
# Fallback: the official Form 2 layout wraps "登記證號碼" (BR number) and
# "費及徵費" (fee/levy) into adjacent table-header cells that a scanned
# copy's OCR reconstruction runs together with no separator
# ("登記證號碼費及徵費"), pushing the actual number several rows further
# down than the label-adjacency pattern above expects. The number itself
# has a distinctive, unlikely-to-collide-elsewhere shape (CRN-000-YY-YY-N)
# and is searched for directly rather than anchored on the broken label.
_BR_NUMBER_SHAPE_RE = re.compile(r"\b([0-9]{7,8}-[0-9]{3}-[0-9]{2}-[0-9]{2}-[0-9])\b")
# Field labels that mark the end of the address block.
_ADDRESS_STOP_RE = re.compile(
    r"(?:Nature of Business|Date of|New Registration|Certificate|Status|"
    r"業務性質|法律地位|發證日期|生效日期|屆滿日期|登記證號碼|"
    r"Effective Date|Particulars)",
    re.IGNORECASE,
)
# Boilerplate/ordinance text that sometimes sits between the document
# header and the actual address field — never part of the address itself.
_ADDRESS_NOISE_RE = re.compile(
    r"ORDINANCE|REGULATION|FORM\s*2|CARE\s*OF|NOT\s*ACCEPTABLE|"
    r"POST\s*OFFICE\s*BOX|ORIGINAL|DUPLICATE|商業登記條例|商業登記規例",
    re.IGNORECASE,
)
# The address field's label: "Business Address" / "經營地址" /
# "Registered Address" (compound forms), or a bare "地址" / "Address" —
# each optionally followed inline by the first fragment of the value, e.g.
# the official Form 2 layout "地 址 RM 509, 5/F THE CLOUD 111". Matched
# near the start of a line (bounded prefix, not a strict `^` anchor) so
# it can't match "business address" appearing mid-sentence in disclaimer
# text, but still catches a scanned copy's OCR reconstruction bleeding
# the *previous* field's tail text onto the same row as this label
# ("Branch Name   當地址香港...", where "地址" starts a few characters in).
_ADDRESS_LABEL_LINE_PREFIX_MAX = 20
_ADDRESS_LABEL_RE = re.compile(
    r"(?:Business\s*Address|經營地址|Registered\s*Address|"
    # combined bilingual label on one line, e.g. "Address / 地址"
    r"地\s*址\s*/\s*Address|Address\s*/\s*地\s*址|"
    r"地\s*址|Address)"
    r"[ \t]*[:：]?[ \t]*",
    re.IGNORECASE,
)
# Scanned-copy OCR artifacts that show up interleaved with real address
# text -- a misread "Address:" fragment, or stray table-border glyphs
# ("!", "|") -- stripped out of every captured fragment rather than
# excluding the whole line, since real address text usually still shares
# that line.
_ADDRESS_ARTIFACT_RE = re.compile(r"\bAddre:?|[!|]", re.IGNORECASE)


def _find_address_label(line: str) -> re.Match | None:
    m = _ADDRESS_LABEL_RE.search(line)
    return m if m and m.start() <= _ADDRESS_LABEL_LINE_PREFIX_MAX else None


def _clean_address_fragment(raw: str) -> str:
    return re.sub(r"\s+", " ", _ADDRESS_ARTIFACT_RE.sub(" ", raw)).strip()


def _is_noise_only_line(line: str) -> bool:
    """A line with no letters/digits/CJK at all -- just stray border
    glyphs or whitespace left over after OCR misreads a ruled table line.
    Skipped (not treated as the end of the address) since real content
    can still follow on a later line."""
    return not re.search(r"[A-Za-z0-9一-鿿]", line)


def _extract_address(text: str) -> str:
    lines = (text or "").split("\n")
    fragments: list[str] = []
    label_seen = False

    i = 0
    while i < len(lines):
        m = _find_address_label(lines[i])
        if not m:
            i += 1
            continue

        # Found the field label. The official Form 2 layout repeats the
        # label on two consecutive lines (Chinese then English), each
        # carrying one fragment of the value on the same line — consume
        # both before moving on to pure continuation lines.
        label_seen = True
        frag = _clean_address_fragment(lines[i][m.end():])
        if frag and not _ADDRESS_NOISE_RE.search(frag):
            fragments.append(frag)
        i += 1

        m2 = _find_address_label(lines[i]) if i < len(lines) else None
        if m2:
            frag2 = _clean_address_fragment(lines[i][m2.end():])
            if frag2 and not _ADDRESS_NOISE_RE.search(frag2):
                fragments.append(frag2)
            i += 1

        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip():
                break
            if _ADDRESS_STOP_RE.search(nxt) or _find_address_label(nxt):
                break
            if _is_noise_only_line(nxt):
                i += 1
                continue
            if not _ADDRESS_NOISE_RE.search(nxt):
                cleaned = _clean_address_fragment(nxt)
                if cleaned:
                    fragments.append(cleaned)
            i += 1
        break

    if not label_seen:
        return ""
    return collapse_line(" ".join(fragments))


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
# Fallback label-only match: the official Form 2's "生效日期"/"屆滿日期"
# (Effective/Expiry Date) header cells run together on a scanned copy
# ("其生效日屆滿日期", missing a 期) with the actual "Date of
# Commencement"/"Date of Expiry" bilingual row -- and its values --
# several rows further down, past the adjacency _DATE_RE expects.
_DATE_LABEL_RE = re.compile(
    r"(?:Date of Commencement(?:\s*of Business)?|Effective Date|生效日期|開業日期)",
    re.IGNORECASE,
)


def extract_br(text: str) -> dict:
    text = text or ""

    trading_m = _TRADING_NAME_RE.search(text)
    trading_name = collapse_line(trading_m.group(1)) if trading_m else ""

    number_m = _BR_NUMBER_RE.search(text)
    br_number = number_m.group(1).strip() if number_m else ""
    if not br_number:
        shape_m = _BR_NUMBER_SHAPE_RE.search(text)
        br_number = shape_m.group(1) if shape_m else ""

    address = _extract_address(text)

    nature_m = _NATURE_RE.search(text)
    nature = collapse_line(nature_m.group(1)) if nature_m else ""

    date_m = _DATE_RE.search(text)
    if date_m:
        effective_date, effective_raw = normalize_date(date_m.group(1))
    else:
        label_m = _DATE_LABEL_RE.search(text)
        effective_date, effective_raw = (
            normalize_date(text[label_m.end():label_m.end() + 200]) if label_m else ("", None)
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
