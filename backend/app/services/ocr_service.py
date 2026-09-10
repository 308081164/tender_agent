"""资质文件 OCR / 文本提取（上传时自动入库）。"""
from __future__ import annotations

import os
import re
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree


def _bundled_tesseract_paths() -> tuple[str | None, str | None]:
    """桌面安装包内置 Tesseract 路径。"""
    install = os.environ.get("TENDER_INSTALL_DIR", "").strip()
    if not install:
        return None, None
    root = Path(install) / "tools" / "tesseract"
    exe = root / "tesseract.exe"
    tessdata = root / "tessdata"
    if exe.is_file():
        return str(exe), str(tessdata) if tessdata.is_dir() else None
    return None, None


def resolve_tesseract_cmd() -> str | None:
    env_cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if env_cmd and os.path.isfile(env_cmd):
        return env_cmd
    bundled, _ = _bundled_tesseract_paths()
    if bundled:
        return bundled
    for candidate in (
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
    ):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def ocr_runtime_status() -> dict[str, object]:
    cmd = resolve_tesseract_cmd()
    tessdata = os.environ.get("TESSDATA_PREFIX", "").strip()
    if not tessdata:
        _, bundled_data = _bundled_tesseract_paths()
        tessdata = bundled_data or ""
    langs = []
    if tessdata and os.path.isdir(tessdata):
        langs = [p.stem for p in Path(tessdata).glob("*.traineddata")]
    return {
        "tesseract_available": bool(cmd),
        "tesseract_cmd": cmd or "",
        "tessdata_prefix": tessdata,
        "languages": sorted(langs)[:20],
        "chi_sim": "chi_sim" in langs,
        "pillow_available": _pillow_available(),
        "pytesseract_available": _pytesseract_available(),
    }


def _pillow_available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


def _pytesseract_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        return True
    except Exception:
        return False


def _configure_tesseract() -> bool:
    cmd = resolve_tesseract_cmd()
    if not cmd:
        return False
    try:
        import pytesseract  # type: ignore
        pytesseract.pytesseract.tesseract_cmd = cmd
    except Exception:
        pass
    _, bundled_data = _bundled_tesseract_paths()
    if bundled_data and not os.environ.get("TESSDATA_PREFIX"):
        os.environ["TESSDATA_PREFIX"] = bundled_data
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
        body = ""

    if body:
        parts.append(body)
    return " ".join(parts).strip()[:8000]
