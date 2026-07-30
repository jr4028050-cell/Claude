"""Shared "raw field strings -> schema'd person fields dict" builder.

Both director/shareholder parsers in this package need the exact same
downstream logic once they've each got hold of the raw strings for a
person's name/ID/address — ID-priority (HKID unless it's blank, else
passport), the romanization fallback when the English name is blank, and
the schema/status wrapping. The two parsers differ only in *how* they get
those raw strings:

- `nnc1.py`'s legacy path regex-matches labels in the flattened text
  stream (used for OCR'd/scanned pages and any document without a
  recognisable PI-NNC1 page).
- `pi_nnc1.py` crops the PI-NNC1 "Protected Information" page by
  coordinate, anchored on each field's printed label.

Keeping the "build the fields dict" step here, shared by both, means that
behaviour never has to be kept in sync by hand across two copies.
"""
from __future__ import annotations

import re

from . import romanize, schema
from .normalize import looks_masked

_HK_ID_BLANK_VALUES = ("NIL", "無")


def split_chinese_name(name: str) -> tuple[str, str]:
    if not name:
        return "", ""
    name = name.strip()
    if len(name) == 1:
        return name, ""
    return name[0], name[1:]


def clean_hkid_value(raw: str) -> str:
    """A filled-in HKID cell reads back its raw text; a blank one is
    marked "NIL" (older forms) or "無" (the current official template) —
    optionally still carrying the empty "( )" check-digit box next to it.
    Strip that box before testing, but return the *original* raw string
    when it turns out not to be blank (the box, if any, is decorative)."""
    cleaned = re.sub(r"[\(\)（）\s]+", "", raw or "")
    return "" if not cleaned or cleaned.upper() in _HK_ID_BLANK_VALUES else raw


def looks_like_china(country: str) -> bool:
    c = re.sub(r"\s+", "", (country or "")).lower()
    return c in ("china", "中国", "中國", "prc", "peoplesrepublicofchina", "mainlandchina")


def classify_id_kind(hkid: str, passport_number: str, issuing_country: str) -> str | None:
    if hkid:
        return "hk"
    if passport_number and looks_like_china(issuing_country):
        return "china"
    return None


def build_person_fields(
    surname_en: str,
    given_en: str,
    chinese_name: str,
    residential_address: str,
    hkid: str,
    passport_number: str,
    issuing_country: str,
    source: str,
    id_info_fallback: str = "",
) -> dict:
    """`id_info_fallback` is a generic "Identification: ..." value to use
    only when neither an HKID nor a passport number was found — for
    non-PI-NNC1 layouts that record some other ID string without the
    HKID/passport structure. The PI-NNC1 coordinate path never has one,
    since every PI-NNC1 page has the HKID/passport fields by construction."""
    surname_cn, given_cn = split_chinese_name(chinese_name)

    if hkid:
        id_info, id_issuing_country = hkid, "Hong Kong"
    elif passport_number:
        id_info, id_issuing_country = passport_number, issuing_country
    elif id_info_fallback:
        id_info, id_issuing_country = id_info_fallback, ""
    else:
        id_info, id_issuing_country = "", ""

    id_status = schema.STATUS_MISSING
    if id_info:
        id_status = schema.STATUS_MASKED if looks_masked(id_info) else schema.STATUS_EXTRACTED

    surname_field = schema.extracted(surname_en, source) if surname_en else schema.missing()
    given_field = schema.extracted(given_en, source) if given_en else schema.missing()

    # English name left blank on the document -> suggest a romanization of
    # the Chinese name, picking the scheme by the ID actually on file.
    # Always flagged for human confirmation, never treated as extracted.
    if not surname_en and not given_en and chinese_name:
        id_kind = classify_id_kind(hkid, passport_number, issuing_country)
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
