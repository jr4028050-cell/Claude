"""NNC1 (incorporation form) / NAR1 (annual return) field extraction.

Provides the registered office address plus one block per director /
founder member. Layout is inherently the least standardised of the three
document types (free-text sections, repeating director blocks), so this
parser leans on label anchoring rather than fixed coordinates. Real sample
forms should be used to calibrate the label variants further — see PRD
第 10.5 节.
"""
from __future__ import annotations

import re

from . import schema
from .normalize import (
    clean_whitespace,
    collapse_line,
    looks_masked,
    normalize_date,
)

_REG_OFFICE_RE = re.compile(
    r"(?:Registered Office(?:\s*Address)?|注[冊册]辦事處地址|注册办事处地址)"
    r"\s*[:.]?\s*\n?"
    r"([^\n]+(?:\n(?!\s*(?:Director|Founder|董事|創辦|创办|Section|Particulars of|"
    r"Shareholder|股東))[^\n]+){0,3})",
    re.IGNORECASE,
)

# A new director/member block starts at each occurrence of this label.
_BLOCK_START_RE = re.compile(
    r"(?:Surname\s*(?:or\s*Company\s*Name)?|姓氏)\s*[:.]?",
    re.IGNORECASE,
)

_STOP_SECTION_RE = re.compile(
    r"\n\s*(?:Particulars of Shares|Shareholder|股東|Statement|聲明|Signature|簽署)",
    re.IGNORECASE,
)

_CJK_RE = re.compile(r"[一-鿿]{2,4}")


def _grab_line(block: str, *label_patterns: str) -> str:
    for lp in label_patterns:
        pat = re.compile(lp + r"\s*[:.]?\s*\n?\s*([^\n]+)", re.IGNORECASE)
        m = pat.search(block)
        if m:
            val = collapse_line(m.group(1))
            if val:
                return val
    return ""


def _extract_registered_office(text: str, source: str) -> dict:
    m = _REG_OFFICE_RE.search(text)
    address = collapse_line(m.group(1)) if m else ""
    return schema.extracted(address, source) if address else schema.missing()


def _split_director_blocks(text: str) -> list[str]:
    starts = [m.start() for m in _BLOCK_START_RE.finditer(text)]
    if not starts:
        return []
    stop_m = _STOP_SECTION_RE.search(text)
    end_limit = stop_m.start() if stop_m else len(text)
    blocks = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else end_limit
        if end <= start:
            continue
        blocks.append(text[start:end])
    return blocks


def _split_chinese_name(name: str) -> tuple[str, str]:
    if not name:
        return "", ""
    name = name.strip()
    if len(name) == 1:
        return name, ""
    return name[0], name[1:]


def _parse_director_block(block: str, source: str) -> dict:
    surname_en = _grab_line(block, r"Surname(?:\s*or\s*Company\s*Name)?")
    given_en = _grab_line(block, r"Forename\(?s?\)?", r"Given\s*Name\(?s?\)?")
    chinese_name = _grab_line(block, r"Chinese\s*Name", r"中文姓名")
    if not chinese_name:
        cjk_m = _CJK_RE.search(block)
        chinese_name = cjk_m.group(0) if cjk_m else ""
    surname_cn, given_cn = _split_chinese_name(chinese_name)

    residential_address = _grab_line(
        block, r"(?:Usual\s*)?Residential\s*Address", r"住[址所]"
    )
    if not residential_address:
        # addresses often wrap onto following lines; grab a small multiline window
        m = re.search(
            r"(?:Usual\s*)?Residential\s*Address\s*[:.]?\s*\n?"
            r"([^\n]+(?:\n(?!\s*(?:Nationality|Identification|國籍|身份))[^\n]+){0,3})",
            block,
            re.IGNORECASE,
        )
        residential_address = collapse_line(m.group(1)) if m else ""

    id_info = _grab_line(
        block, r"Identification", r"I\.?D\.?\s*No\.?", r"身份證明文件", r"身份证明文件"
    )

    dob_raw = _grab_line(block, r"Date\s*of\s*Birth", r"出生日期")
    dob, dob_raw_clean = normalize_date(dob_raw) if dob_raw else ("", None)

    id_status = schema.STATUS_MISSING
    if id_info:
        id_status = schema.STATUS_MASKED if looks_masked(id_info) else schema.STATUS_EXTRACTED

    return {
        "surname_cn": schema.extracted(surname_cn, source) if surname_cn else schema.missing(),
        "given_cn": schema.extracted(given_cn, source) if given_cn else schema.missing(),
        "surname_en": schema.extracted(surname_en, source) if surname_en else schema.missing(),
        "given_en": schema.extracted(given_en, source) if given_en else schema.missing(),
        "residential_address": (
            schema.extracted(residential_address, source) if residential_address else schema.missing()
        ),
        "id_issuing_country": schema.missing(),  # needs ID document upload; see PRD 10.1
        "dob": (
            schema.extracted(dob, source, raw=dob_raw_clean) if dob else schema.missing()
        ),
        "id_info": (
            schema.field(id_info, source, id_status) if id_info else schema.missing()
        ),
    }


def extract_nnc1(text: str, source: str = "NNC1") -> dict:
    text = clean_whitespace(text or "")

    registered_address = _extract_registered_office(text, source)

    blocks = _split_director_blocks(text)
    directors = [_parse_director_block(b, source) for b in blocks]
    # drop blocks that yielded essentially nothing (false-positive label match)
    directors = [
        d for d in directors
        if d["surname_en"]["value"] or d["given_en"]["value"] or d["residential_address"]["value"]
    ]

    return {
        "registered_address": registered_address,
        "directors": directors,
    }
