"""NNC1 (incorporation form) / NAR1 (annual return) field extraction.

Provides the registered office address, one block per director, and the
computed UBO (beneficial owner) list. Layout is inherently the least
standardised of the three document types (free-text sections, repeating
director/shareholder blocks), so this parser leans on label anchoring
rather than fixed coordinates. Real sample forms should be used to
calibrate the label variants further — see PRD 第 10.5 节.
"""
from __future__ import annotations

import re

from . import schema
from .normalize import clean_whitespace, collapse_line, looks_masked

UBO_THRESHOLD_PCT = 25.0

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
# A new corporate shareholder block starts here (no personal "Surname").
_CORP_BLOCK_START_RE = re.compile(
    r"(?:Name\s*of\s*Corporation|Corporation\s*Name|法團名稱|公司名稱)\s*[:.]?",
    re.IGNORECASE,
)

_STOP_SECTION_RE = re.compile(
    r"\n\s*(?:Particulars of Shares|Shareholder|股東|Statement|聲明|Signature|簽署)",
    re.IGNORECASE,
)

_CJK_RE = re.compile(r"[一-鿿]{2,4}")

_COMPANY_SUFFIX_RE = re.compile(
    r"\b(LIMITED|LTD\.?|INC\.?|CORP\.?|HOLDINGS?|GROUP|CO\.,?\s*LTD\.?)\b",
    re.IGNORECASE,
)

# Founder-member/shareholder blocks carry a shares-taken field that plain
# director blocks don't — this is what distinguishes the two, wherever in
# the document each block physically sits.
_SHARES_TAKEN_RE = re.compile(
    r"(?:Number\s*(?:and\s*Class\s*)?of\s*Shares(?:\s*Taken)?|"
    r"認購股份數目|认购股份数目|股份數目|股份数目|Shares\s*Taken|No\.?\s*of\s*Shares)"
    r"\s*[:.]?\s*\n?\s*([0-9][0-9,]*)",
    re.IGNORECASE,
)

# Denominator: NNC1 第5节 "Share Capital and Initial Shareholdings" Total
# row / NAR1's issued-shares total.
_TOTAL_SHARES_RE = re.compile(
    r"(?:Total\s*Number\s*of\s*Shares\s*Proposed\s*to\s*be\s*Issued|"
    r"建議發行的股份總數|建议发行的股份总数|"
    r"Total\s*Number\s*of\s*Issued\s*Shares|已發行股份總數|已发行股份总数|"
    r"Total\s*Number\s*of\s*Shares)"
    r"\s*[:.]?\s*\n?\s*([0-9][0-9,]*)",
    re.IGNORECASE,
)
# Fallback: the label and the number sit in different table cells/rows —
# take the first plausible (3+ digit) number within a short window after
# the label instead of requiring it immediately adjacent.
_TOTAL_SHARES_LABEL_RE = re.compile(
    r"(?:Total\s*Number\s*of\s*Shares\s*Proposed\s*to\s*be\s*Issued|"
    r"建議發行的股份總數|建议发行的股份总数|"
    r"Total\s*Number\s*of\s*Issued\s*Shares|已發行股份總數|已发行股份总数)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\b([0-9][0-9,]{2,})\b")


def _grab_line(block: str, *label_patterns: str) -> str:
    for lp in label_patterns:
        pat = re.compile(lp + r"\s*[:.]?\s*\n?\s*([^\n]+)", re.IGNORECASE)
        m = pat.search(block)
        if m:
            val = collapse_line(m.group(1))
            if val:
                return val
    return ""


def _parse_int(raw: str) -> int:
    return int(raw.replace(",", ""))


def _extract_registered_office(text: str, source: str) -> dict:
    m = _REG_OFFICE_RE.search(text)
    address = collapse_line(m.group(1)) if m else ""
    return schema.extracted(address, source) if address else schema.missing()


def _extract_total_shares(text: str) -> int | None:
    m = _TOTAL_SHARES_RE.search(text)
    if m:
        return _parse_int(m.group(1))

    label_m = _TOTAL_SHARES_LABEL_RE.search(text)
    if not label_m:
        return None
    window = text[label_m.end():label_m.end() + 300]
    num_m = _NUMBER_RE.search(window)
    return _parse_int(num_m.group(1)) if num_m else None


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


def _parse_person_fields(block: str, source: str) -> dict:
    """Name/ID/address common to both a director entry and an individual
    shareholder entry."""
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
    id_status = schema.STATUS_MISSING
    if id_info:
        id_status = schema.STATUS_MASKED if looks_masked(id_info) else schema.STATUS_EXTRACTED

    return {
        "surname_en": surname_en,
        "given_en": given_en,
        "surname_cn": surname_cn,
        "given_cn": given_cn,
        "fields": {
            "surname_cn": schema.extracted(surname_cn, source) if surname_cn else schema.missing(),
            "given_cn": schema.extracted(given_cn, source) if given_cn else schema.missing(),
            "surname_en": schema.extracted(surname_en, source) if surname_en else schema.missing(),
            "given_en": schema.extracted(given_en, source) if given_en else schema.missing(),
            "residential_address": (
                schema.extracted(residential_address, source) if residential_address else schema.missing()
            ),
            "id_info": (
                schema.field(id_info, source, id_status) if id_info else schema.missing()
            ),
        },
    }


def _parse_director_block(block: str, source: str) -> dict:
    return _parse_person_fields(block, source)["fields"]


def _looks_like_company_name(name: str) -> bool:
    return bool(name) and bool(_COMPANY_SUFFIX_RE.search(name))


def _find_shareholders(text: str, source: str) -> list[dict]:
    """Scan the whole document for founder-member/shareholder entries —
    identified by carrying a "Number of Shares" field, wherever they
    physically sit (a distinct '創辦成員/Founder Members' section on real
    forms, separate from both the director particulars and the Section 5
    share-capital totals table).
    """
    starts: list[tuple[int, str]] = []
    for m in _BLOCK_START_RE.finditer(text):
        starts.append((m.start(), "person"))
    for m in _CORP_BLOCK_START_RE.finditer(text):
        starts.append((m.start(), "corporate"))
    starts.sort(key=lambda x: x[0])

    shareholders = []
    for i, (start, kind) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        if end <= start:
            continue
        block = text[start:end]

        shares_m = _SHARES_TAKEN_RE.search(block)
        if not shares_m:
            continue  # no shareholding info in this block -> not a shareholder entry
        shares = _parse_int(shares_m.group(1))

        if kind == "corporate":
            name = _grab_line(
                block, r"Name\s*of\s*Corporation", r"Corporation\s*Name", r"法團名稱", r"公司名稱"
            )
            if not name:
                continue
            shareholders.append({"is_corporate": True, "name": name, "shares": shares, "source": source})
            continue

        person = _parse_person_fields(block, source)
        # some forms label the corporate shareholder's name field "Surname
        # or Company Name" too; detect that case via the company-suffix
        # heuristic (no forename, name ends in Limited/Ltd/Inc/...).
        if not person["given_en"] and _looks_like_company_name(person["surname_en"]):
            shareholders.append({
                "is_corporate": True,
                "name": person["surname_en"],
                "shares": shares,
                "source": source,
            })
            continue

        if not (person["surname_en"] or person["given_en"] or person["surname_cn"]):
            continue

        shareholders.append({
            "is_corporate": False,
            "fields": person["fields"],
            "shares": shares,
            "source": source,
        })

    return shareholders


def _name_key(surname_en: str, given_en: str) -> str:
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().upper())
    return norm(surname_en) + "|" + norm(given_en)


def _backfill_shareholder_identity(shareholders: list[dict], directors: list[dict]) -> None:
    """Founder-member/shareholder blocks on real forms usually only carry
    the name + shares-taken figure — full ID/address is recorded once, in
    that person's director particulars. Since it's common for a small HK
    company's majority owner to also be its sole director, backfill ID/
    address (and any Chinese name) from a matching director record so the
    UBO entry isn't left blank for data that's actually in the document.
    """
    by_key = {}
    for d in directors:
        key = _name_key(d["surname_en"]["value"], d["given_en"]["value"])
        if key.strip("|"):
            by_key[key] = d

    for sh in shareholders:
        if sh["is_corporate"]:
            continue
        f = sh["fields"]
        d = by_key.get(_name_key(f["surname_en"]["value"], f["given_en"]["value"]))
        if not d:
            continue
        for k in ("residential_address", "id_info", "surname_cn", "given_cn"):
            if not f[k]["value"] and d[k]["value"]:
                f[k] = d[k]


def _format_pct(pct: float) -> str:
    return f"{pct:.2f}%"


def _build_ubos(shareholders: list[dict], total_shares: int | None, source: str) -> list[dict]:
    ubos = []
    for sh in shareholders:
        if total_shares:
            pct = sh["shares"] / total_shares * 100
            pct_field = schema.field(_format_pct(pct), source, schema.STATUS_EXTRACTED)
            qualifies = pct >= UBO_THRESHOLD_PCT
        else:
            # can't compute the ratio without a denominator; surface the
            # shareholder anyway (flagged) rather than silently dropping a
            # potential beneficial owner — see PRD follow-up on UBO 判定.
            pct_field = schema.missing()
            qualifies = True

        if not qualifies:
            continue

        if sh["is_corporate"]:
            ubo = {
                "is_corporate": True,
                "surname_cn": schema.na(),
                "given_cn": schema.na(),
                "surname_en": schema.na(),
                "given_en": schema.na(),
                "company_name": schema.extracted(sh["name"], source),
                "residential_address": schema.na(),
                "id_info": schema.na(),
                "shareholding_pct": pct_field,
            }
        else:
            f = sh["fields"]
            ubo = {
                "is_corporate": False,
                "surname_cn": f["surname_cn"],
                "given_cn": f["given_cn"],
                "surname_en": f["surname_en"],
                "given_en": f["given_en"],
                "company_name": schema.na(),
                "residential_address": f["residential_address"],
                "id_info": f["id_info"],
                "shareholding_pct": pct_field,
            }
        ubos.append(ubo)
    return ubos


def extract_nnc1(text: str, source: str = "NNC1") -> dict:
    text = clean_whitespace(text or "")

    registered_address = _extract_registered_office(text, source)

    blocks = _split_director_blocks(text)
    # A block that also carries a "Number of Shares" field belongs to the
    # founder-member/shareholder listing, not the director particulars,
    # even when the same person's name shows up there too (common case).
    director_blocks = [b for b in blocks if not _SHARES_TAKEN_RE.search(b)]
    directors = [_parse_director_block(b, source) for b in director_blocks]
    # drop blocks that yielded essentially nothing (false-positive label match)
    directors = [
        d for d in directors
        if d["surname_en"]["value"] or d["given_en"]["value"] or d["residential_address"]["value"]
    ]

    total_shares = _extract_total_shares(text)
    shareholders = _find_shareholders(text, source)
    _backfill_shareholder_identity(shareholders, directors)
    ubos = _build_ubos(shareholders, total_shares, source)

    return {
        "registered_address": registered_address,
        "directors": directors,
        "ubos": ubos,
    }
