"""运行环境自检：Aspose / OCR / AI / 文档引擎 / 存储等。"""
from __future__ import annotations

import os
import shutil
from typing import Any

from sqlalchemy.orm import Session

from app.services import settings_svc
from app.services.ocr_service import ocr_runtime_status


def _check_aspose() -> dict[str, Any]:
    try:
        from app.services.aspose_runtime import smoke_test
        info = smoke_test()
        return {"id": "aspose", "name": "Aspose.Words 文档引擎", "status": "ok", "detail": info}
    except Exception as exc:
        return {"id": "aspose", "name": "Aspose.Words 文档引擎", "status": "error", "detail": str(exc)}


def _check_ocr() -> dict[str, Any]:
    st = ocr_runtime_status()
    status = "ok" if st.get("tesseract_available") else "warn"
    return {"id": "ocr", "name": "资质 OCR (Tesseract)", "status": status, "detail": st}


def _check_onlyoffice() -> dict[str, Any]:
    from app.services import onlyoffice as oo
    payload = oo.status_payload()
    enabled = bool(payload.get("enabled"))
    return {
        "id": "onlyoffice",
        "name": "OnlyOffice 在线编辑",
        "status": "ok" if enabled else "info",
        "detail": payload,
    }


def _check_ai(db: Session | None) -> dict[str, Any]:
    cfg = settings_svc.resolve_ai_config(db) if db else {}
    ds = bool(cfg.get("deepseek_api_key"))
    qw = bool(cfg.get("qwen_api_key"))
    model = cfg.get("deepseek_model") or settings_svc.DEEPSEEK_DEFAULT_MODEL
    if ds or qw:
        return {
            "id": "ai",
            "name": "AI 模型 API",
            "status": "ok",
            "detail": {
                "deepseek_configured": ds,
                "qwen_configured": qw,
                "deepseek_model": model,
                "preferred_provider": cfg.get("preferred_provider") or "auto",
            },
        }
    return {
        "id": "ai",
        "name": "AI 模型 API",
        "status": "warn",
        "detail": "未配置 DeepSeek / 通义千问 Key，智能创作将回退本地模板引擎",
    }


def _check_doc_engine() -> dict[str, Any]:
    try:
        from app.services.doc_engine.manifest import MANIFEST_VERSION
        from app.services.doc_engine import sdt, tables, bundles, qual_insert, ocr_match  # noqa: F401
        return {
            "id": "doc_engine",
            "name": "文档引擎 v2",
            "status": "ok",
            "detail": {"manifest_version": MANIFEST_VERSION, "modules": "loaded"},
        }
    except Exception as exc:
        return {"id": "doc_engine", "name": "文档引擎 v2", "status": "error", "detail": str(exc)}


def _check_libreoffice() -> dict[str, Any]:
    soffice = os.environ.get("SOFFICE_PATH") or shutil.which("soffice")
    if soffice:
        return {"id": "libreoffice", "name": "LibreOffice (PDF 预览兜底)", "status": "ok", "detail": soffice}
    return {
        "id": "libreoffice",
        "name": "LibreOffice (PDF 预览兜底)",
        "status": "info",
        "detail": "未检测到 soffice，PDF 预览将优先使用 Aspose",
    }


def run_system_check(db: Session | None = None) -> dict[str, Any]:
    checks = [
        _check_aspose(),
        _check_ocr(),
        _check_doc_engine(),
        _check_ai(db),
        _check_onlyoffice(),
        _check_libreoffice(),
    ]
    errors = [c for c in checks if c.get("status") == "error"]
    warns = [c for c in checks if c.get("status") == "warn"]
    overall = "red" if errors else ("yellow" if warns else "green")
    return {
        "status": overall,
        "summary": {
            "ok": sum(1 for c in checks if c.get("status") == "ok"),
            "warn": len(warns),
            "error": len(errors),
            "info": sum(1 for c in checks if c.get("status") == "info"),
        },
        "checks": checks,
        "desktop_mode": os.environ.get("TENDER_DESKTOP") == "1",
    }
