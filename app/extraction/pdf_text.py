"""PDF text extraction with OCR fallback for scanned files.

Text-layer PDFs are read word-by-word with pdfplumber and reconstructed
into lines by spatial position (row = clustered `top`, columns ordered by
`x0`) rather than using pdfplumber's default `extract_text()`, which
reconstructs reading order from the PDF content stream's character order.
On multi-column forms (e.g. the PI-NNC1 director particulars page, which
lays a Chinese label, its English label, and the filled-in value out in
separate columns/rows) that content-stream order does not match the
visual layout, so labels and values end up scrambled into each other by
the time they reach `nnc1.py`'s field regexes. Rebuilding from word
bounding boxes keeps each label lined up with the value beside or below
it. If a PDF's text layer is too thin (scanned/image-only), we fall back
to rendering pages to images and running Tesseract OCR with the
Traditional Chinese + English language pack, per PRD 第 7 节, using the
same row/column reconstruction on OCR's word-level bounding boxes.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

import pdfplumber

logger = logging.getLogger(__name__)

# Below this average character count per page, treat the PDF as scanned.
OCR_TRIGGER_CHARS_PER_PAGE = 40
OCR_DPI = 300
OCR_LANG = "chi_tra+eng"

# Row/column reconstruction tolerances, in PDF points (1/72 inch).
_ROW_Y_TOLERANCE_PT = 3.0
_COLUMN_GAP_PT = 15.0
# Same tolerances, scaled from points to pixels at OCR_DPI for the OCR path.
_PT_TO_OCR_PX = OCR_DPI / 72.0
_ROW_Y_TOLERANCE_OCR_PX = _ROW_Y_TOLERANCE_PT * _PT_TO_OCR_PX
_COLUMN_GAP_OCR_PX = _COLUMN_GAP_PT * _PT_TO_OCR_PX


@dataclass
class PageResult:
    text: str
    ocr: bool = False


@dataclass
class DocumentText:
    filename: str
    pages: list[PageResult] = field(default_factory=list)
    ocr_used: bool = False
    warning: str = ""

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)


def _words_to_layout_text(
    words: list[dict], row_y_tolerance: float, column_gap: float
) -> str:
    """Rebuild text from word boxes ({"text", "x0", "x1", "top"}), one
    output line per visual row, preserving left-to-right column order and
    marking column boundaries with extra whitespace.
    """
    if not words:
        return ""

    words = sorted(words, key=lambda w: (w["top"], w["x0"]))

    rows: list[list[dict]] = []
    for w in words:
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= row_y_tolerance:
            rows[-1].append(w)
        else:
            rows.append([w])

    lines = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        parts = []
        prev_x1 = None
        for w in row:
            if prev_x1 is not None:
                gap = w["x0"] - prev_x1
                parts.append("   " if gap > column_gap else " ")
            parts.append(w["text"])
            prev_x1 = w["x1"]
        lines.append("".join(parts))

    return "\n".join(lines)


def _reconstruct_page_text(page) -> str:
    words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False)
    boxes = [{"text": w["text"], "x0": w["x0"], "x1": w["x1"], "top": w["top"]} for w in words]
    return _words_to_layout_text(boxes, _ROW_Y_TOLERANCE_PT, _COLUMN_GAP_PT)


def _extract_text_layer(pdf_bytes: bytes) -> list[str]:
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            pages.append(_reconstruct_page_text(page))
    return pages


def _ocr_page_text(image) -> str:
    import pytesseract

    data = pytesseract.image_to_data(
        image, lang=OCR_LANG, config="--psm 6", output_type=pytesseract.Output.DICT
    )
    boxes = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if not text:
            continue
        x0 = float(data["left"][i])
        top = float(data["top"][i])
        boxes.append({"text": text, "x0": x0, "x1": x0 + float(data["width"][i]), "top": top})
    return _words_to_layout_text(boxes, _ROW_Y_TOLERANCE_OCR_PX, _COLUMN_GAP_OCR_PX)


def _ocr_pages(pdf_bytes: bytes) -> list[str]:
    # Imported lazily: these pull in poppler/tesseract system binaries that
    # may not be installed when only text-layer PDFs are used.
    from pdf2image import convert_from_bytes

    images = convert_from_bytes(pdf_bytes, dpi=OCR_DPI)
    return [_ocr_page_text(img) for img in images]


def extract_document_text(filename: str, pdf_bytes: bytes) -> DocumentText:
    doc = DocumentText(filename=filename)

    try:
        text_pages = _extract_text_layer(pdf_bytes)
    except Exception as exc:  # malformed PDF, encrypted, etc.
        logger.warning("text-layer extraction failed for %s: %s", filename, exc)
        text_pages = []
        doc.warning = f"无法读取文字层：{exc}"

    if text_pages:
        avg_chars = sum(len(p) for p in text_pages) / max(len(text_pages), 1)
    else:
        avg_chars = 0

    if avg_chars >= OCR_TRIGGER_CHARS_PER_PAGE:
        doc.pages = [PageResult(text=t) for t in text_pages]
        return doc

    # scanned / low-text PDF: fall back to OCR
    try:
        ocr_pages = _ocr_pages(pdf_bytes)
        doc.pages = [PageResult(text=t, ocr=True) for t in ocr_pages]
        doc.ocr_used = True
    except Exception as exc:
        logger.warning("OCR failed for %s: %s", filename, exc)
        doc.warning = (
            f"OCR 识别失败（{exc}），已回退为文字层结果，可能字段缺失。"
            " 请确认已安装 tesseract-ocr（含 chi_tra 语言包）与 poppler。"
        )
        doc.pages = [PageResult(text=t) for t in text_pages]

    return doc
