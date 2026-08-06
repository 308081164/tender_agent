"""DOCX → PDF conversion: Aspose (built-in) with LibreOffice fallback."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

SOFFICE_CANDIDATES = (
    os.environ.get("SOFFICE_PATH"),
    "soffice",
    "libreoffice",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)


def find_soffice() -> str | None:
    for candidate in SOFFICE_CANDIDATES:
        if not candidate:
            continue
        if os.path.isabs(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _pdf_converter_pref() -> str:
    return (os.environ.get("PDF_CONVERTER") or "auto").strip().lower()


def get_pdf_engine() -> str | None:
    """Return the engine that would be used: aspose | libreoffice | None."""
    pref = _pdf_converter_pref()
    from app.services import word

    if pref == "libreoffice":
        return "libreoffice" if find_soffice() else None
    if pref == "aspose":
        return "aspose" if word.can_convert_pdf() else None
    if word.can_convert_pdf():
        return "aspose"
    if find_soffice():
        return "libreoffice"
    return None


def pdf_conversion_available() -> bool:
    return get_pdf_engine() is not None


def pdf_object_key(docx_object_key: str) -> str:
    """Derive cached PDF key from DOCX object key."""
    if docx_object_key.lower().endswith(".docx"):
        return docx_object_key[:-5] + ".pdf"
    return docx_object_key + ".pdf"


def _convert_via_aspose(docx_bytes: bytes) -> bytes:
    from app.services import word

    return word.convert_docx_to_pdf(docx_bytes)


def _convert_via_libreoffice(docx_bytes: bytes, timeout: int = 120) -> bytes:
    soffice = find_soffice()
    if not soffice:
        raise RuntimeError(
            "未找到 LibreOffice（soffice）。请安装 libreoffice-writer 或设置 SOFFICE_PATH。"
        )

    with tempfile.TemporaryDirectory(prefix="docx2pdf_") as tmp:
        tmp_path = Path(tmp)
        in_path = tmp_path / "input.docx"
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        in_path.write_bytes(docx_bytes)

        profile_dir = tmp_path / "lo_profile"
        profile_dir.mkdir()
        profile_uri = profile_dir.as_uri()

        cmd = [
            soffice,
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            "--nofirststartwizard",
            f"-env:UserInstallation={profile_uri}",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(out_dir),
            str(in_path),
        ]
        logger.info("LibreOffice convert: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env={**os.environ, "HOME": str(tmp_path)},
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"DOCX→PDF 转换超时（>{timeout}s）") from exc

        pdf_path = out_dir / "input.pdf"
        if result.returncode != 0 or not pdf_path.is_file():
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            detail = stderr or stdout or f"exit={result.returncode}"
            raise RuntimeError(f"LibreOffice DOCX→PDF 失败：{detail}")

        return pdf_path.read_bytes()


def convert_docx_to_pdf(docx_bytes: bytes, timeout: int = 120) -> bytes:
    """
    Convert DOCX bytes to PDF.
    Default order: Aspose (built-in) → LibreOffice (when PDF_CONVERTER=auto).
    """
    pref = _pdf_converter_pref()
    errors: list[str] = []

    if pref in ("auto", "aspose"):
        try:
            pdf_bytes = _convert_via_aspose(docx_bytes)
            logger.info("DOCX→PDF via Aspose (%d bytes)", len(pdf_bytes))
            return pdf_bytes
        except Exception as err:
            errors.append(f"Aspose: {err}")
            if pref == "aspose":
                raise RuntimeError(f"DOCX→PDF 转换失败（Aspose）：{err}") from err

    if pref in ("auto", "libreoffice"):
        try:
            pdf_bytes = _convert_via_libreoffice(docx_bytes, timeout=timeout)
            logger.info("DOCX→PDF via LibreOffice (%d bytes)", len(pdf_bytes))
            return pdf_bytes
        except Exception as err:
            errors.append(f"LibreOffice: {err}")
            if pref == "libreoffice":
                raise RuntimeError(f"DOCX→PDF 转换失败（LibreOffice）：{err}") from err

    detail = "；".join(errors) if errors else "未配置 PDF 转换引擎"
    raise RuntimeError(f"DOCX→PDF 转换失败：{detail}")
