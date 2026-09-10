"""资质文件 OCR / 文本提取（上传时自动入库）。"""
from __future__ import annotations

import re
import zipfile
from io import BytesIO
from xml.etree import ElementTree


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            xml = zf.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        texts = []
        for t in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
            if t.text:
                texts.append(t.text)
        return re.sub(r"\s+", " ", " ".join(texts)).strip()
    except Exception:
        return ""


def _image_ocr(data: bytes) -> str:
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
    """从资质附件提取可检索文本，写入 ocr_text。"""
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
        # 轻量兜底：不引入 PDF 解析库时保留元数据
        body = ""

    if body:
        parts.append(body)
    return " ".join(parts).strip()[:8000]
