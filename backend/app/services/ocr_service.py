"""资质文件 OCR / 文本提取（上传时自动入库）。"""
from __future__ import annotations

import os
import re
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree


def resolve_tesseract_cmd() -> str | None:
    env_cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if env_cmd and os.path.isfile(env_cmd):
        return env_cmd
    for candidate in (
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
    ):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _configure_tesseract() -> bool:
    cmd = resolve_tesseract_cmd()
    if not cmd:
        return False
    try:
        import pytesseract  # type: ignore
        pytesseract.pytesseract.tesseract_cmd = cmd
    except Exception:
        pass
    return True


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            xml = zf.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        texts = []
        for t in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
            if t.text:
                texts.append(t.text)
        return re.sub(r"\s+", " ", " ".join(texts)).strip()
    except Exception:
        return ""


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(BytesIO(data))
        parts = []
        for page in reader.pages[:30]:
            t = page.extract_text() or ""
            if t.strip():
                parts.append(t.strip())
        return re.sub(r"\s+", " ", " ".join(parts)).strip()
    except Exception:
        return ""


def _image_ocr(data: bytes) -> str:
    if not _configure_tesseract():
        return ""
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
        img = Image.open(BytesIO(data))
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        return re.sub(r"\s+", " ", (text or "").strip())
    except Exception:
        return ""


def extract_text_from_file(
    data: bytes,
    file_type: str,
    *,
    name: str = "",
    keywords: str = "",
    category: str = "",
) -> str:
    """从资质附件提取可检索文本。"""
    ftype = (file_type or "").lower().lstrip(".")
    parts: list[str] = []
    for p in (name, category, keywords):
        if p and str(p).strip():
            parts.append(str(p).strip())

    body = ""
    if ftype in ("jpg", "jpeg", "png", "bmp", "gif", "webp", "tif", "tiff"):
        body = _image_ocr(data)
    elif ftype == "docx":
        body = _docx_text(data)
    elif ftype == "pdf":
        body = _pdf_text(data)

    if body:
        parts.append(body)
    return " ".join(parts).strip()[:8000]
