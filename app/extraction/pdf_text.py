"""PDF text extraction with OCR fallback for scanned files.

Text-layer PDFs are read with pdfplumber (keeps layout, good for anchoring
labels). If a PDF's text layer is too thin (scanned/image-only), we fall
back to rendering pages to images and running Tesseract OCR with the
Traditional Chinese + English language pack, per PRD 第 7 节.
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


def _extract_text_layer(pdf_bytes: bytes) -> list[str]:
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return pages


def _ocr_pages(pdf_bytes: bytes) -> list[str]:
    # Imported lazily: these pull in poppler/tesseract system binaries that
    # may not be installed when only text-layer PDFs are used.
    from pdf2image import convert_from_bytes
    import pytesseract

    images = convert_from_bytes(pdf_bytes, dpi=OCR_DPI)
    return [pytesseract.image_to_string(img, lang=OCR_LANG) for img in images]


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
