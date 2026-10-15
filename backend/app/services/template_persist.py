"""上传即存档：收下 docx 和文件里已经写好的 {{key}}，不进入占位符编辑器。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Template
from app.services import storage, word
from app.services.docx_ooxml import paragraph_records


def _empty_section_titles(data: bytes) -> list[str]:
    try:
        records = paragraph_records(data)
    except Exception:
        return []
    titles: list[str] = []
    for idx, rec in enumerate(records):
        style = (rec.get("style") or "")
        text = (rec.get("text") or "").strip()
        heading = style.lower().startswith("heading") or "标题" in style
        if not heading or not text or len(text) > 40:
            continue
        nxt = records[idx + 1] if idx + 1 < len(records) else None
        nxt_text = ((nxt or {}).get("text") or "").strip()
        if nxt is not None and len(nxt_text) > 30:
            continue
        titles.append(text)
    return titles


def infer_template_kind(data: bytes) -> str:
    """空白或半空白走骨架；已经写满的标书走历史替换。"""
    titles = _empty_section_titles(data)
    try:
        records = paragraph_records(data)
    except Exception:
        records = []
    long_paras = [rec for rec in records if len((rec.get("text") or "").strip()) > 40]
    if len(titles) >= 2 and len(long_paras) <= 1:
        return "skeleton"
    if titles and not long_paras:
        return "skeleton"
    return "history"


def persist_uploaded_template(
    db: Session,
    data: bytes,
    filename: str,
    *,
    name: str = "",
    kind: str = "template",
    template_code: str = "common",
    description: str = "",
) -> Template:
    """把 docx 存成可再次选用的模板。已有 {{key}} 由系统收下，用户不必画。"""
    fname = filename or "uploaded.docx"
    resolved_kind = infer_template_kind(data) if kind in ("", "auto") else kind
    key = f"templates/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{fname}"
    storage.upload_bytes(
        key,
        data,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    ph_list = word.safe_extract_placeholders(data)
    ph_meta: dict = {"list": ph_list}
    if resolved_kind == "skeleton":
        ph_meta["ai_reference_full_doc"] = True
    try:
        from app.services.docx_ooxml import aspose_available
        if aspose_available():
            from app.services.doc_engine.engine import attach_manifest_to_template
            from app.services.doc_engine.parser import parse_template_manifest

            manifest = parse_template_manifest(data, is_history=resolved_kind == "history")
            ph_meta = attach_manifest_to_template(ph_meta, manifest)
    except Exception as exc:
        print(f"[upload] manifest analyze warn: {exc}")
    upload_desc = {
        "history": "基于完整标书上传：文件已存档，已有占位符由系统收下。立项后进入创作时替换项目名称、招标编号和金额。",
        "skeleton": "基于空白模板上传：文件已存档。空章节在进入创作时识别，可直接开始写。",
        "template": "上传的可复用模板。",
    }
    tpl = Template(
        name=(name or fname)[:200],
        description=description or upload_desc.get(resolved_kind, "上传模板"),
        object_key=key,
        placeholders=ph_meta,
        template_code=template_code or "common",
        kind=resolved_kind,
        enabled=True,
        source_snapshot={},
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


def template_choice_dict(tpl: Template) -> dict:
    """新建标书选择器需要的字段。"""
    from app.services.project_workflow import resolve_template_mode

    ph_list = (tpl.placeholders or {}).get("list") or []
    mode_info = resolve_template_mode(tpl)
    return {
        "id": tpl.id,
        "name": tpl.name,
        "description": tpl.description,
        "placeholders": tpl.placeholders or {},
        "is_history": bool((tpl.placeholders or {}).get("is_history")) or tpl.kind == "history",
        "template_code": tpl.template_code or "common",
        "kind": tpl.kind or "template",
        "enabled": bool(tpl.enabled),
        "placeholder_count": len(ph_list),
        "workflow_mode": mode_info.get("mode") or "compose",
        "workflow_label": mode_info.get("label") or "",
        "object_key": tpl.object_key,
    }
