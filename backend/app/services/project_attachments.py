"""项目多格式附件上传与文本抽取。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import TenderProject
from app.services import storage, word
from app.services.field_verify import is_verify_field, SENSITIVE_FIELD_KEYS
from app.models import FieldDef


def _guess_field_patch(text: str, db: Session) -> list[dict[str, Any]]:
    """轻量规则 + 关键词，返回 suggested_field_patch（非 LLM 降级）。"""
    suggestions: list[dict] = []
    import re

    patterns = [
        (r"招标编号[：:\s]*([A-Za-z0-9\-/]{4,40})", "tender_no", 0.85),
        (r"项目名称[：:\s]*(.{2,80})", "project_name", 0.8),
        (r"招标人[：:\s]*(.{2,60})", "tenderer", 0.75),
    ]
    for pat, key, conf in patterns:
        m = re.search(pat, text)
        if m:
            suggestions.append({
                "key": key,
                "value": m.group(1).strip()[:200],
                "confidence": conf,
                "sensitive": key in SENSITIVE_FIELD_KEYS,
            })
    return suggestions


async def ingest_attachment(
    db: Session,
    project: TenderProject,
    filename: str,
    data: bytes,
    content_type: str = "",
) -> dict[str, Any]:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    att_id = uuid.uuid4().hex[:12]
    key = f"projects/{project.id}/attachments/{att_id}_{filename}"
    storage.upload_bytes(key, data, content_type or "application/octet-stream")

    extracted = ""
    kind = ext or "unknown"
    try:
        if ext in ("txt", "md"):
            extracted = data.decode("utf-8", errors="ignore")[:50000]
        elif ext == "docx":
            preview = word.extract_preview(data, max_paragraphs=200)
            extracted = "\n".join(p.get("text") or "" for p in preview.get("paragraphs") or [])
        elif ext in ("pdf", "png", "jpg", "jpeg", "webp", "gif", "bmp"):
            from app.services import ocr_service

            extracted = ocr_service.extract_text_from_file(data, ext, name=filename)[:50000]
            if ext != "pdf":
                kind = "image"
    except Exception as err:
        extracted = f"[解析失败: {err}]"

    patch = _guess_field_patch(extracted, db)
    for item in patch:
        fd = db.query(FieldDef).filter(FieldDef.key == item["key"]).first()
        if fd and is_verify_field(fd):
            item["sensitive"] = True
            item["auto_apply"] = False
        else:
            item["auto_apply"] = item.get("confidence", 0) >= 0.82 and not item.get("sensitive")

    fields = dict(project.fields or {})
    attachments = list(fields.get("_attachments") or [])
    record = {
        "id": att_id,
        "name": filename,
        "type": kind,
        "object_key": key,
        "extracted_text": extracted[:8000],
        "created_at": datetime.utcnow().isoformat(),
        "suggested_field_patch": patch,
    }
    attachments.append(record)
    fields["_attachments"] = attachments[-50:]
    project.fields = fields
    flag_modified(project, "fields")
    project.updated_at = datetime.utcnow()
    db.commit()

    return {
        "attachment": record,
        "suggested_field_patch": patch,
        "extracted_preview": extracted[:1500],
    }
