"""Cross-file merge: applies PRD 第 5 节的 priority/default/derive/conflict
rules to turn per-file extraction results into the final enterprise +
representatives payload described in PRD 第 6 节.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import schema
from .normalize import guess_country_from_address


@dataclass
class NNC1Source:
    filename: str
    doc_kind: str  # "NAR1" or "NNC1"
    data: dict
    recency_key: str = ""  # e.g. an extracted "made up to" date; used to pick the newest NAR1


def _norm_key(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().upper())


def _field_count_filled(director: dict) -> int:
    return sum(1 for f in director.values() if f.get("value"))


def _director_key(director: dict) -> str:
    return _norm_key(director["surname_en"]["value"]) + "|" + _norm_key(director["given_en"]["value"])


def _pick_reg_address(nnc1_sources: list[NNC1Source]) -> tuple[dict, list[dict]]:
    """Registered address: prefer the newest NAR1, else fall back to NNC1."""
    candidates = [s for s in nnc1_sources if s.data["registered_address"]["value"]]
    if not candidates:
        return schema.missing(), []

    nar1_candidates = [s for s in candidates if s.doc_kind == "NAR1"]
    pool = nar1_candidates or candidates
    chosen_source = sorted(pool, key=lambda s: s.recency_key)[-1]
    chosen = chosen_source.data["registered_address"]

    distinct_values = {_norm_key(s.data["registered_address"]["value"]) for s in candidates}
    conflicts = []
    if len(distinct_values) > 1:
        conflicts.append({
            "field": "enterprise.reg_address",
            "chosen": chosen["value"],
            "chosen_source": chosen_source.filename,
            "candidates": [
                {"value": s.data["registered_address"]["value"], "source": s.filename}
                for s in candidates
            ],
        })
    return chosen, conflicts


def _merge_directors(nnc1_sources: list[NNC1Source]) -> list[dict]:
    """Merge director blocks across all NNC1/NAR1 files. When the same person
    appears more than once (matched on English name), keep whichever record
    is more complete, preferring the newest NAR1 on ties.
    """
    # NNC1 files processed first, newest NAR1 processed last so it
    # overwrites older duplicates
    ordered = sorted(
        [s for s in nnc1_sources if s.doc_kind != "NAR1"], key=lambda s: s.recency_key
    ) + sorted(
        [s for s in nnc1_sources if s.doc_kind == "NAR1"], key=lambda s: s.recency_key
    )

    merged: dict[str, dict] = {}
    order: list[str] = []
    for source in ordered:
        for director in source.data["directors"]:
            key = _director_key(director)
            if not key.strip("|"):
                continue
            existing = merged.get(key)
            if existing is None or _field_count_filled(director) >= _field_count_filled(existing):
                merged[key] = director
            if key not in order:
                order.append(key)
    return [merged[k] for k in order]


def merge(
    ci_files: list[tuple[str, dict]],
    br_files: list[tuple[str, dict]],
    nnc1_sources: list[NNC1Source],
) -> dict:
    conflicts: list[dict] = []

    # --- enterprise: name_en (CI, fallback: none extracted elsewhere) ---
    name_en = schema.missing()
    for _, ci in ci_files:
        if ci["name_en"]["value"]:
            name_en = ci["name_en"]
            break

    # --- crn / incorp_date: CI only ---
    crn = schema.missing()
    incorp_date = schema.missing()
    for _, ci in ci_files:
        if ci["crn"]["value"] and not crn["value"]:
            crn = ci["crn"]
        if ci["incorp_date"]["value"] and not incorp_date["value"]:
            incorp_date = ci["incorp_date"]

    # --- trading name: BR business name, fallback to name_en ---
    trading_name = schema.missing()
    for _, br in br_files:
        if br["trading_name"]["value"]:
            trading_name = br["trading_name"]
            break
    if not trading_name["value"] and name_en["value"]:
        trading_name = schema.inferred(name_en["value"], "name_en")

    # --- reg_country / reg_city: rule defaults, always ---
    reg_country = schema.default("Hong Kong / 中国香港")
    reg_city = schema.default("Hong Kong")

    # --- reg_address: latest NAR1 > NNC1 ---
    reg_address, addr_conflicts = _pick_reg_address(nnc1_sources)
    conflicts.extend(addr_conflicts)
    if not reg_address["value"]:
        # fall back to BR's address if nothing from NNC1/NAR1
        for _, br in br_files:
            if br["business_address"]["value"]:
                reg_address = schema.inferred(br["business_address"]["value"], "BR")
                break

    # --- operating country / address: BR, else default / inferred from reg_address ---
    business_address = schema.missing()
    for _, br in br_files:
        if br["business_address"]["value"]:
            business_address = br["business_address"]
            break

    if business_address["value"]:
        op_country_value = guess_country_from_address(business_address["value"]) or "Hong Kong"
        op_country = schema.extracted(op_country_value, "BR")
        op_address = business_address
    else:
        op_country = schema.default("Hong Kong")
        if reg_address["value"]:
            op_address = schema.inferred(reg_address["value"], "reg_address")
        else:
            op_address = schema.missing()

    enterprise = {
        "name_en": name_en,
        "trading_name": trading_name,
        "crn": crn,
        "incorp_date": incorp_date,
        "reg_country": reg_country,
        "reg_city": reg_city,
        "reg_address": reg_address,
        "op_country": op_country,
        "op_address": op_address,
    }

    representatives = _merge_directors(nnc1_sources)

    files = (
        [f for f, _ in ci_files]
        + [f for f, _ in br_files]
        + [s.filename for s in nnc1_sources]
    )

    return {
        "enterprise": enterprise,
        "representatives": representatives,
        "conflicts": conflicts,
        "files": files,
    }
