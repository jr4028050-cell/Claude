"""Generic word-search + coordinate-crop helpers shared by every
coordinate-based field extractor in this package (`pi_nnc1.py` for the
PI-NNC1 director page, `registered_office.py` for NNC1's own registered-
office address block). Kept free of any document-specific field lists or
label vocabulary -- those live with each caller.
"""
from __future__ import annotations

from .normalize import collapse_line


def find_word(words: list[dict], keyword: str, y_min: float = 0.0) -> dict | None:
    """First word (in the already top-to-bottom, left-to-right sorted
    `words` list) at or below `y_min` whose text contains `keyword`
    (case-insensitive substring)."""
    kw = keyword.lower()
    for w in words:
        if w["top"] >= y_min - 0.1 and kw in w["text"].lower():
            return w
    return None


def find_word_any(words: list[dict], keywords: tuple[str, ...], y_min: float = 0.0) -> dict | None:
    """`find_word` trying each keyword in turn, returning the first hit."""
    for kw in keywords:
        w = find_word(words, kw, y_min)
        if w is not None:
            return w
    return None


def crop_value(
    page, anchor_top: float, floor: float, x0: float, x1: float,
    window_above: float, window_below: float,
) -> str:
    """Crop a small box near `anchor_top` (spanning `window_above` pt
    above it to `window_below` pt below it, clamped to never go above
    `floor`) within the `[x0, x1]` column, and return its collapsed text.
    """
    top = max(anchor_top - window_above, floor + 1.0, 0.0)
    bottom = min(anchor_top + window_below, page.height)
    x0 = max(x0, 0.0)
    x1 = min(x1, page.width)
    if top >= bottom or x0 >= x1:
        return ""
    box = page.crop((x0, top, x1, bottom))
    return collapse_line(box.extract_text() or "")
