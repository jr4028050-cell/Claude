"""Chinese-name romanization fallback for English name fields left blank
on the source document.

Two distinct confidence levels, per explicit product requirement:
- Mandarin Hanyu Pinyin (via `pypinyin`) is a deterministic, standardised
  transliteration -> surfaced as an "inferred" value.
- Cantonese/Hong Kong-ID-style romanization has no standardised scheme
  (the English name on an HKID is whatever the holder originally
  registered, which frequently doesn't match any phonetic system) -> the
  jyutping-based approximation here is only ever a suggestion, and must be
  surfaced as "unconfirmed" for a human to verify against the actual ID.
"""
from __future__ import annotations

try:
    import pypinyin
except ImportError:  # pragma: no cover - optional dependency
    pypinyin = None

try:
    import pycantonese
except ImportError:  # pragma: no cover - optional dependency
    pycantonese = None


def _split_name(name: str) -> tuple[str, str]:
    name = (name or "").strip()
    if not name:
        return "", ""
    if len(name) == 1:
        return name, ""
    return name[0], name[1:]


def mandarin_pinyin_name(chinese_name: str) -> tuple[str, str] | None:
    """Standard Hanyu Pinyin, e.g. 邱漢城 -> ("Qiu", "Hancheng")."""
    if not pypinyin or not chinese_name:
        return None
    surname_cn, given_cn = _split_name(chinese_name)
    if not surname_cn:
        return None

    surname = "".join(
        s[0] for s in pypinyin.pinyin(surname_cn, style=pypinyin.Style.NORMAL)
    ).capitalize()
    given = ""
    if given_cn:
        given = "".join(
            s[0] for s in pypinyin.pinyin(given_cn, style=pypinyin.Style.NORMAL)
        ).capitalize()
    return (surname, given) if surname else None


# Rough jyutping-initial -> HK-ID-style-romanization map. Approximate only;
# real HKID English names are not a deterministic function of pronunciation.
_JYUTPING_INITIALS_BY_LENGTH = ("ng", "gw", "kw", "b", "p", "m", "f", "d", "t",
                                "n", "l", "g", "k", "h", "w", "z", "c", "s", "j")
_JYUTPING_INITIAL_MAP = {
    "b": "P", "p": "P", "m": "M", "f": "F",
    "d": "T", "t": "T", "n": "N", "l": "L",
    "g": "K", "k": "K", "ng": "Ng", "h": "H",
    "gw": "Kw", "kw": "Kw", "w": "W",
    "z": "Ch", "c": "Ch", "s": "S", "j": "Y",
}


def _jyutping_syllable_to_hk_style(syllable: str) -> str:
    body = syllable.rstrip("0123456789")
    if not body:
        return ""
    for initial in _JYUTPING_INITIALS_BY_LENGTH:
        if body.startswith(initial):
            final = body[len(initial):]
            roman_initial = _JYUTPING_INITIAL_MAP[initial]
            if initial == "s" and final.startswith("i"):
                roman_initial = "Sh"  # common HK-style spelling quirk (si -> shi)
            return (roman_initial + final).capitalize()
    return body.capitalize()


def _jyutping_syllables(chinese_fragment: str) -> list[str]:
    if not chinese_fragment:
        return []
    try:
        pairs = pycantonese.characters_to_jyutping(chinese_fragment)
    except Exception:
        return []
    syllables: list[str] = []
    for _, jp in pairs:
        if jp:
            syllables.extend(jp.split())
    return syllables


def cantonese_suggested_name(chinese_name: str) -> tuple[str, str] | None:
    """Unconfirmed HK-ID-style suggestion, e.g. 邱漢城 -> ("Yau", "Hon Shing").
    Callers MUST mark this as needing manual verification, never as a
    confirmed extracted value.
    """
    if not pycantonese or not chinese_name:
        return None
    surname_cn, given_cn = _split_name(chinese_name)
    surname_syllables = _jyutping_syllables(surname_cn)
    if not surname_syllables:
        return None
    surname = "".join(_jyutping_syllable_to_hk_style(s) for s in surname_syllables)
    given_syllables = _jyutping_syllables(given_cn)
    given = " ".join(_jyutping_syllable_to_hk_style(s) for s in given_syllables)
    return (surname, given) if surname else None
