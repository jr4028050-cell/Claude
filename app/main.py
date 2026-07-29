"""FastAPI backend for the HK entity material extraction tool.

Serves the static frontend and exposes POST /api/extract, which accepts the
three upload windows described in PRD 第 3 节 (CI / BR / NNC1·NAR1), runs
text/OCR extraction + rule-based field parsing, merges results per PRD 第 5
节, and returns the JSON payload described in PRD 第 6 节.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.extraction import br as br_rules
from app.extraction import ci as ci_rules
from app.extraction import nnc1 as nnc1_rules
from app.extraction.merge import NNC1Source, merge
from app.extraction.normalize import normalize_date
from app.extraction.pdf_text import extract_document_text

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="HK 主体材料信息提取")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

MAX_FILE_SIZE_MB = 20

_NAR1_HINT_RE = re.compile(r"Annual\s*Return|周年申報表|周年申报表", re.IGNORECASE)
_NNC1_HINT_RE = re.compile(
    r"Incorporation\s*Form|法團成立表格|法团成立表格|NNC1", re.IGNORECASE
)
_MADE_UP_TO_RE = re.compile(
    r"made up to\s*[:.]?\s*"
    r"([0-9]{1,2}[/\-. ][A-Za-z0-9]{1,9}[/\-. ][0-9]{4}|"
    r"[0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2})",
    re.IGNORECASE,
)


def _classify_nnc1_kind(filename: str, text: str) -> str:
    if _NAR1_HINT_RE.search(text) or "nar1" in filename.lower():
        return "NAR1"
    if _NNC1_HINT_RE.search(text) or "nnc1" in filename.lower():
        return "NNC1"
    return "NNC1"


def _recency_key(text: str, upload_index: int) -> str:
    m = _MADE_UP_TO_RE.search(text)
    if m:
        iso, _ = normalize_date(m.group(1))
        if iso:
            return iso
    # no date found: fall back to upload order so the last-uploaded file
    # of the same kind wins ties, matching "同类可多份，取最新" 的假设
    return f"0000-00-{upload_index:02d}"


async def _read_upload(upload: UploadFile) -> tuple[str, bytes, str]:
    data = await upload.read()
    warning = ""
    size_mb = len(data) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        warning = f"{upload.filename} 大小 {size_mb:.1f}MB，超过建议的 {MAX_FILE_SIZE_MB}MB，提取可能较慢。"
    return upload.filename or "unnamed.pdf", data, warning


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/extract")
async def extract(
    ci_files: list[UploadFile] = File(default=[]),
    br_files: list[UploadFile] = File(default=[]),
    nnc1_files: list[UploadFile] = File(default=[]),
) -> dict:
    warnings: list[str] = []

    ci_results = []
    for upload in ci_files:
        filename, data, warn = await _read_upload(upload)
        if warn:
            warnings.append(warn)
        doc = extract_document_text(filename, data)
        if doc.warning:
            warnings.append(f"{filename}: {doc.warning}")
        ci_results.append((filename, ci_rules.extract_ci(doc.full_text)))

    br_results = []
    for upload in br_files:
        filename, data, warn = await _read_upload(upload)
        if warn:
            warnings.append(warn)
        doc = extract_document_text(filename, data)
        if doc.warning:
            warnings.append(f"{filename}: {doc.warning}")
        br_results.append((filename, br_rules.extract_br(doc.full_text)))

    nnc1_sources: list[NNC1Source] = []
    for idx, upload in enumerate(nnc1_files):
        filename, data, warn = await _read_upload(upload)
        if warn:
            warnings.append(warn)
        doc = extract_document_text(filename, data)
        if doc.warning:
            warnings.append(f"{filename}: {doc.warning}")
        doc_kind = _classify_nnc1_kind(filename, doc.full_text)
        parsed = nnc1_rules.extract_nnc1(doc.full_text, source=doc_kind)
        nnc1_sources.append(
            NNC1Source(
                filename=filename,
                doc_kind=doc_kind,
                data=parsed,
                recency_key=_recency_key(doc.full_text, idx),
            )
        )

    if not ci_results and not br_results and not nnc1_sources:
        return {
            "enterprise": {},
            "representatives": [],
            "conflicts": [],
            "files": [],
            "warnings": ["未收到任何文件"],
        }

    result = merge(ci_results, br_results, nnc1_sources)
    result["warnings"] = warnings
    return result
