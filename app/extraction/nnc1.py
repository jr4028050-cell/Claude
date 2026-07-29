"""NNC1 (incorporation form) / NAR1 (annual return) field extraction.

Provides the registered office address, one block per director, and the
computed UBO (beneficial owner) list. Layout is inherently the least
standardised of the three document types (free-text sections, repeating
director/shareholder blocks), so this parser leans on label anchoring
rather than fixed coordinates.

Director particulars are commonly recorded on a "PI-NNC1" style page per
person (首任公司秘書／董事(自然人)- 受保護資料 / First Company Secretary /
Director) with bilingual field labels: 中文姓名/Name in Chinese, then
Surname/Other Names under 英文姓名/Name in English, an Identification
block (Hong Kong ID, or a passport's Full Number + Issuing Country when
the HKID cell is "NIL"), and a Usual Residential Address broken into
Flat/Floor/Block, Building, Street, District/City/Province, Country. Every
value grab below is guarded by `_is_label_noise` so a blank field can never
be mistaken for the label text sitting next to it (see `_grab_line`).
"""
from __future__ import annotations

import re

from . import romanize, schema
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
# On a PI-NNC1-style page, 中文姓名 is listed *before* Surname/Other Names;
# widen a director block backward to include it when it's close by.
_CHINESE_NAME_LABEL_RE = re.compile(
    r"中文姓名(?:\s*/\s*Name\s*in\s*Chinese)?|Name\s*in\s*Chinese",
    re.IGNORECASE,
)
# The PI-NNC1 attachment's page heading — one such page is one person's
# full particulars. When present, this is the block boundary: it is far
# more specific than scanning for a bare "Surname"/"姓氏" occurrence, which
# can also appear in unrelated sections (e.g. a proposed-company-name
# field asking for an "English or Chinese" name) and would otherwise be
# mistaken for a second director.
_PI_NNC1_PAGE_RE = re.compile(
    r"首任公司秘書／?董事\s*\(自然人\)|"
    r"First\s*Company\s*Secretary\s*/\s*Director\s*\(Individual\)",
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

# ---- PI-NNC1 field labels ----
_ADDR_SECTION_RE = re.compile(
    r"董事的通常住址|Usual\s*Residential\s*Address(?:\s*of\s*Director)?",
    re.IGNORECASE,
)
_ADDR_FLAT_LABELS = (r"Flat\s*/\s*Floor\s*/\s*Block", r"室\s*/?\s*樓\s*/?\s*座")
_ADDR_BUILDING_LABELS = (r"Building", r"大廈")
_ADDR_STREET_LABELS = (r"Street", r"街道")
_ADDR_DISTRICT_LABELS = (r"District\s*/\s*City\s*/\s*Province", r"地區\s*/?\s*市\s*/?\s*省")
_ADDR_COUNTRY_LABELS = (r"Country", r"國家")

_HKID_LABELS = (
    r"香港身份證(?:號碼)?", r"Hong\s*Kong\s*Identity\s*Card(?:\s*No\.?)?", r"HKID",
)
_PASSPORT_FULL_NUMBER_LABELS = (r"完整號碼", r"Full\s*Number")
_ISSUING_COUNTRY_LABELS = (r"簽發國家(?:\s*/\s*地區)?", r"Issuing\s*Country(?:\s*/\s*Region)?")

# Every label fragment used elsewhere in this module, plus a few
# page-level headings/captions. A captured "value" made up entirely of one
# or more of these — a lone label, or a bilingual pair like "身分識別 /
# Identification" on one line and its English restatement "Hong Kong
# Identity Card No." on the next — is rejected outright. This is the core
# safety net: it guards against a blank cell whose "value" capture landed
# on the next field's label instead of on actual filled-in content.
_LABEL_FRAGMENTS = [
    r"Surname(?:\s*or\s*Company\s*Name)?", r"姓氏",
    r"Other\s*Names?", r"Forename\(?s?\)?", r"Given\s*Name\(?s?\)?", r"名字",
    r"前用姓名", r"曾用姓名", r"Former\s*Name\(?s?\)?",
    r"中文姓名", r"Name\s*in\s*Chinese", r"Chinese\s*Name",
    r"英文姓名", r"Name\s*in\s*English",
    r"建議採用的公司英文或中文名稱", r"建议采用的公司英文或中文名称",
    r"Proposed\s*Company\s*(?:English\s*or\s*Chinese|Chinese\s*or\s*English)\s*Name",
    r"或\s*OR", r"in\s*Hong\s*Kong", r"elsewhere",
    r"身分識別", r"身份識別", r"Identification",
    r"香港身份證(?:號碼)?", r"Hong\s*Kong\s*Identity\s*Card(?:\s*No\.?)?", r"HKID",
    r"護照", r"Passport",
    r"完整號碼", r"Full\s*Number",
    r"簽發國家(?:\s*/\s*地區)?", r"Issuing\s*Country(?:\s*/\s*Region)?",
    r"董事的通常住址", r"通常住址", r"Usual\s*Residential\s*Address(?:\s*of\s*Director)?",
    r"of\s*Director", r"Director", r"董事",
    r"Flat\s*/\s*Floor\s*/\s*Block", r"室\s*/?\s*樓\s*/?\s*座",
    r"Building", r"大廈", r"Street", r"街道",
    r"District\s*/\s*City\s*/\s*Province", r"地區\s*/?\s*市\s*/?\s*省",
    r"Country", r"國家",
    r"PI-NNC1", r"首任公司秘書／?董事(?:\s*\(自然人\))?",
    r"First\s*Company\s*Secretary\s*/\s*Director(?:\s*\(Individual\))?",
    r"受保護資料", r"Protected\s*Information",
    r"NIL",
]
_LABEL_FRAGMENT_ALT = "(?:" + "|".join(_LABEL_FRAGMENTS) + ")"
# a "value" that is nothing but one or more label fragments (optionally
# bilingual-paired with / ， ,) is noise, not real content
_LABEL_NOISE_RE = re.compile(
    r"^\s*" + _LABEL_FRAGMENT_ALT + r"(?:\s*[/／,，]\s*" + _LABEL_FRAGMENT_ALT + r")*\s*$",
    re.IGNORECASE,
)
# Parenthetical instructional asides ("(Please state the full address in
# Hong Kong or elsewhere)") sit right next to several PI-NNC1 fields and
# must never be captured as if they were the filled-in value.
_INSTRUCTION_NOISE_RE = re.compile(
    r"^\s*\(.*\)\s*$|Please\s*state|not\s*acceptable|Post\s*Office\s*Box",
    re.IGNORECASE,
)


def _is_label_noise(value: str) -> bool:
    if not value:
        return False
    return bool(_LABEL_NOISE_RE.match(value) or _INSTRUCTION_NOISE_RE.search(value))


def _grab_line(block: str, *label_patterns: str) -> str:
    for lp in label_patterns:
        pat = re.compile(lp + r"\s*[:.]?\s*\n?\s*([^\n]+)", re.IGNORECASE)
        m = pat.search(block)
        if m:
            val = collapse_line(m.group(1))
            if val and not _is_label_noise(val):
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


def _dedupe_close_starts(positions: list[int], min_gap: int = 30) -> list[int]:
    """`_BLOCK_START_RE` matches both "Surname" and the bare Chinese "姓氏"
    independently, so a bilingual pair like "姓氏\\nSurname" yields two
    positions a few characters apart for what is really one field/block
    boundary. Collapse any positions closer than `min_gap` into a single
    one (keeping the later, more specific match), so the block doesn't get
    fragmented and the 中文姓名 backward-widening search isn't clipped by a
    spurious empty block in between.
    """
    if not positions:
        return []
    positions = sorted(positions)
    deduped = [positions[0]]
    for p in positions[1:]:
        if p - deduped[-1] < min_gap:
            deduped[-1] = p
        else:
            deduped.append(p)
    return deduped


def _split_by_positions(text: str, starts: list[int], end_limit: int) -> list[str]:
    blocks = []
    for i, s_start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else end_limit
        if end <= s_start:
            continue
        blocks.append(text[s_start:end])
    return blocks


def _split_director_blocks(text: str) -> list[str]:
    stop_m = _STOP_SECTION_RE.search(text)
    end_limit = stop_m.start() if stop_m else len(text)

    # Primary: one PI-NNC1 attachment page = one director. Scoping to the
    # page heading means field lookups below never wander into an
    # unrelated section (a proposed-company-name field, a different
    # director's page, ...) and mistake its label text for this person's
    # data — the exact failure mode this design fixes.
    page_starts = [m.start() for m in _PI_NNC1_PAGE_RE.finditer(text)]
    if page_starts:
        return _split_by_positions(text, page_starts, end_limit)

    # Fallback: no PI-NNC1 attachment page found — the older, simpler
    # "Surname or Company Name" table-row format (one row per director,
    # no dedicated per-person page).
    surname_starts = _dedupe_close_starts([m.start() for m in _BLOCK_START_RE.finditer(text)])
    if not surname_starts:
        return []

    blocks = []
    prev_end = 0
    for i, s_start in enumerate(surname_starts):
        end = surname_starts[i + 1] if i + 1 < len(surname_starts) else end_limit
        if end <= s_start:
            continue
        # 中文姓名 is listed *before* Surname/Other Names on some layouts;
        # widen the block backward to include it, without stealing text
        # already claimed by the previous block.
        block_start = s_start
        search_from = max(prev_end, s_start - 400)
        last_cn_label = None
        for cm in _CHINESE_NAME_LABEL_RE.finditer(text, search_from, s_start):
            last_cn_label = cm.start()
        if last_cn_label is not None:
            block_start = last_cn_label
        blocks.append(text[block_start:end])
        prev_end = end
    return blocks


def _split_chinese_name(name: str) -> tuple[str, str]:
    if not name:
        return "", ""
    name = name.strip()
    if len(name) == 1:
        return name, ""
    return name[0], name[1:]


_ADDR_FLAT_LABEL_RE = re.compile("|".join(_ADDR_FLAT_LABELS), re.IGNORECASE)


def _grab_pi_nnc1_address(block: str) -> str:
    m = _ADDR_SECTION_RE.search(block)
    if not m:
        return ""
    sub_block = block[m.end():]
    # Only treat this as the PI-NNC1 component layout (Flat/Floor/Block,
    # Building, Street, ...) when that first sub-label genuinely follows
    # close by. Otherwise this is the simpler "Residential Address: value"
    # layout, and grabbing "Street"/"Country" against it risks matching
    # those words where they appear *inside* the address value itself
    # (e.g. "...STREET" in "20 BAKER STREET") rather than as a label —
    # leave it for `_grab_generic_address` to handle instead.
    # 200 chars, not 80: some forms insert an instructional note ("Please
    # state the full address in Hong Kong or elsewhere") between the
    # heading and the first sub-label.
    if not _ADDR_FLAT_LABEL_RE.search(sub_block[:200]):
        return ""
    parts = [
        _grab_line(sub_block, *_ADDR_FLAT_LABELS),
        _grab_line(sub_block, *_ADDR_BUILDING_LABELS),
        _grab_line(sub_block, *_ADDR_STREET_LABELS),
        _grab_line(sub_block, *_ADDR_DISTRICT_LABELS),
        _grab_line(sub_block, *_ADDR_COUNTRY_LABELS),
    ]
    return ", ".join(p for p in parts if p)


def _grab_generic_address(block: str) -> str:
    address = _grab_line(
        block, r"(?:Usual\s*)?Residential\s*Address(?:\s*of\s*Director)?", r"住[址所]"
    )
    if address:
        return address
    m = re.search(
        r"(?:Usual\s*)?Residential\s*Address(?:\s*of\s*Director)?\s*[:.]?\s*\n?"
        r"([^\n]+(?:\n(?!\s*(?:Nationality|Identification|國籍|身份))[^\n]+){0,3})",
        block,
        re.IGNORECASE,
    )
    candidate = collapse_line(m.group(1)) if m else ""
    return candidate if candidate and not _is_label_noise(candidate) else ""


def _grab_hkid(block: str) -> str:
    val = _grab_line(block, *_HKID_LABELS)
    return "" if not val or val.strip().upper() == "NIL" else val


def _grab_passport_number(block: str) -> str:
    return _grab_line(block, *_PASSPORT_FULL_NUMBER_LABELS)


def _grab_issuing_country(block: str) -> str:
    return _grab_line(block, *_ISSUING_COUNTRY_LABELS)


def _looks_like_china(country: str) -> bool:
    c = re.sub(r"\s+", "", (country or "")).lower()
    return c in ("china", "中国", "中國", "prc", "peoplesrepublicofchina", "mainlandchina")


def _classify_id_kind(hkid: str, passport_number: str, issuing_country: str) -> str | None:
    if hkid:
        return "hk"
    if passport_number and _looks_like_china(issuing_country):
        return "china"
    return None


def _parse_person_fields(block: str, source: str) -> dict:
    """Name/ID/address common to both a director entry and an individual
    shareholder entry."""
    surname_en = _grab_line(block, r"Surname(?:\s*or\s*Company\s*Name)?")
    given_en = _grab_line(
        block, r"Other\s*Names?", r"Forename\(?s?\)?", r"Given\s*Name\(?s?\)?"
    )
    chinese_name = _grab_line(
        block, r"中文姓名(?:\s*/\s*Name\s*in\s*Chinese)?", r"Name\s*in\s*Chinese", r"Chinese\s*Name"
    )
    if not chinese_name:
        cjk_m = _CJK_RE.search(block)
        chinese_name = cjk_m.group(0) if cjk_m else ""
    surname_cn, given_cn = _split_chinese_name(chinese_name)

    residential_address = _grab_pi_nnc1_address(block) or _grab_generic_address(block)

    hkid = _grab_hkid(block)
    passport_number = _grab_passport_number(block)
    issuing_country = _grab_issuing_country(block)

    if hkid:
        id_info, id_issuing_country = hkid, "Hong Kong"
    elif passport_number:
        id_info, id_issuing_country = passport_number, issuing_country
    else:
        id_info = _grab_line(
            block, r"Identification", r"I\.?D\.?\s*No\.?", r"身份證明文件", r"身份证明文件"
        )
        id_issuing_country = ""

    id_status = schema.STATUS_MISSING
    if id_info:
        id_status = schema.STATUS_MASKED if looks_masked(id_info) else schema.STATUS_EXTRACTED

    surname_field = schema.extracted(surname_en, source) if surname_en else schema.missing()
    given_field = schema.extracted(given_en, source) if given_en else schema.missing()

    # English name left blank on the document -> suggest a romanization of
    # the Chinese name, picking the scheme by the ID actually on file.
    # Always flagged for human confirmation, never treated as extracted.
    if not surname_en and not given_en and chinese_name:
        id_kind = _classify_id_kind(hkid, passport_number, issuing_country)
        if id_kind == "china":
            guess = romanize.mandarin_pinyin_name(chinese_name)
            if guess:
                g_surname, g_given = guess
                surname_field = schema.inferred(g_surname, "拼音推断")
                given_field = schema.inferred(g_given, "拼音推断") if g_given else schema.missing()
        elif id_kind == "hk":
            guess = romanize.cantonese_suggested_name(chinese_name)
            if guess:
                g_surname, g_given = guess
                surname_field = schema.suggested(g_surname, "粤语拼音建议·待确认")
                given_field = (
                    schema.suggested(g_given, "粤语拼音建议·待确认") if g_given else schema.missing()
                )

    return {
        "surname_en": surname_en,
        "given_en": given_en,
        "surname_cn": surname_cn,
        "given_cn": given_cn,
        "fields": {
            "surname_cn": schema.extracted(surname_cn, source) if surname_cn else schema.missing(),
            "given_cn": schema.extracted(given_cn, source) if given_cn else schema.missing(),
            "surname_en": surname_field,
            "given_en": given_field,
            "residential_address": (
                schema.extracted(residential_address, source) if residential_address else schema.missing()
            ),
            "id_info": (
                schema.field(id_info, source, id_status) if id_info else schema.missing()
            ),
            "id_issuing_country": (
                schema.extracted(id_issuing_country, source) if id_issuing_country else schema.missing()
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
    starts: list[tuple[int, str]] = [
        (pos, "person")
        for pos in _dedupe_close_starts([m.start() for m in _BLOCK_START_RE.finditer(text)])
    ]
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
        for k in ("residential_address", "id_info", "id_issuing_country", "surname_cn", "given_cn"):
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
                "id_issuing_country": schema.na(),
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
                "id_issuing_country": f["id_issuing_country"],
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
