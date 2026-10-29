"""Agent 文档 Map 工具：读 outline、填表单元格、单元格插图。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services import storage
from app.services.doc_engine.document_map import (
    OUTLINE_FIELD,
    build_document_map,
    compact_outline_for_agent,
    merge_outline_into_fields,
    read_section_payload,
)


def _load_session_docx(session) -> tuple[bytes | None, dict[str, Any], str]:
    ws = dict(getattr(session, "workspace", None) or {})
    doc_key = ws.get("draft_object_key") or ws.get("template_object_key") or ""
    if not doc_key:
        return None, ws, ""
    try:
        data = storage.download_bytes(doc_key)
    except Exception:
        return None, ws, doc_key
    return data, ws, doc_key


def _manifest_for_session(db: Session | None, ws: dict[str, Any]) -> dict[str, Any]:
    from app.models import Template, TenderProject

    tpl_id = ws.get("template_id")
    project_id = ws.get("project_id")
    if not tpl_id and project_id and db is not None:
        p = db.query(TenderProject).filter(TenderProject.id == int(project_id)).first()
        if p and p.template_id:
            tpl_id = p.template_id
    if not tpl_id or db is None:
        return {}
    tpl = db.query(Template).filter(Template.id == int(tpl_id)).first()
    if not tpl:
        return {}
    from app.services.doc_engine.manifest import get_manifest

    return get_manifest(tpl.placeholders) or {}


def _persist_outline_ws(ws: dict[str, Any], doc_bytes: bytes, manifest: dict[str, Any]) -> dict[str, Any]:
    doc_map = build_document_map(doc_bytes, manifest)
    ws = dict(ws)
    ws[OUTLINE_FIELD] = doc_map
    return ws, doc_map


def _store_docx(db: Session | None, session, ws: dict[str, Any], new_bytes: bytes, suffix: str) -> str:
    from datetime import datetime

    saved = f"chat/{getattr(session, 'id', 0)}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{suffix}.docx"
    storage.upload_bytes(
        saved,
        new_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    ws = dict(ws)
    ws["draft_object_key"] = saved
    ws["version"] = int(ws.get("version") or 0) + 1
    session.workspace = ws
    if db is not None:
        db.commit()
    return saved


def read_document_outline(
    db: Session | None,
    session,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    doc_bytes, ws, doc_key = _load_session_docx(session)
    if not doc_bytes:
        cached = (ws.get(OUTLINE_FIELD) or {})
        if cached and not refresh:
            return {"ok": True, "outline": compact_outline_for_agent(cached), "cached": True}
        return {"ok": False, "error": "工作区没有打开的标书 DOCX"}
    manifest = _manifest_for_session(db, ws)
    if not refresh and ws.get(OUTLINE_FIELD):
        return {
            "ok": True,
            "object_key": doc_key,
            "outline": compact_outline_for_agent(ws.get(OUTLINE_FIELD)),
            "cached": True,
        }
    doc_map = build_document_map(doc_bytes, manifest)
    ws, _ = _persist_outline_ws(ws, doc_bytes, manifest)
    session.workspace = ws
    if db is not None:
        db.commit()
    return {
        "ok": True,
        "object_key": doc_key,
        "outline": compact_outline_for_agent(doc_map),
        "cached": False,
    }


def read_document_section(
    db: Session | None,
    session,
    heading_title: str,
) -> dict[str, Any]:
    doc_bytes, ws, doc_key = _load_session_docx(session)
    if not doc_bytes:
        return {"ok": False, "error": "工作区没有打开的标书 DOCX"}
    payload = read_section_payload(doc_bytes, heading_title)
    if not payload.get("ok"):
        return payload
    payload["object_key"] = doc_key
    return payload


def list_empty_form_slots(
    db: Session | None,
    session,
) -> dict[str, Any]:
    doc_bytes, ws, doc_key = _load_session_docx(session)
    if not doc_bytes:
        return {"ok": False, "error": "工作区没有打开的标书 DOCX", "slots": []}
    manifest = _manifest_for_session(db, ws)
    doc_map = build_document_map(doc_bytes, manifest)
    slots = doc_map.get("empty_slots") or []
    return {
        "ok": True,
        "object_key": doc_key,
        "count": len(slots),
        "slots": slots[:50],
    }


def fill_table_cells(
    db: Session | None,
    session,
    cells: list[dict[str, Any]],
) -> dict[str, Any]:
    from app.services.doc_engine.indexer import replace_at_location

    doc_bytes, ws, doc_key = _load_session_docx(session)
    if not doc_bytes:
        return {"ok": False, "error": "工作区没有打开的标书 DOCX"}
    if not cells:
        return {"ok": False, "error": "cells 不能为空"}
    applied: list[dict[str, Any]] = []
    data = doc_bytes
    for item in cells[:40]:
        if not isinstance(item, dict):
            continue
        loc = str(item.get("location") or "").strip()
        text = str(item.get("text") or item.get("value") or "")
        if not loc:
            ti = item.get("table_index")
            row = item.get("row")
            col = item.get("col")
            if ti is not None and row is not None and col is not None:
                loc = f"tbl:{int(ti)}:r{int(row)}:c{int(col)}"
        if not loc or not loc.startswith("tbl:"):
            continue
        data = replace_at_location(data, loc, text)
        applied.append({"location": loc, "text": text[:200]})
    if not applied:
        return {"ok": False, "error": "没有有效的单元格坐标"}
    manifest = _manifest_for_session(db, ws)
    saved = _store_docx(db, session, ws, data, "fill_cells")
    ws = dict(session.workspace or {})
    ws, doc_map = _persist_outline_ws(ws, data, manifest)
    session.workspace = ws
    if db is not None:
        db.commit()
    return {
        "ok": True,
        "modified": True,
        "object_key": saved,
        "applied": applied,
        "outline": compact_outline_for_agent(doc_map),
        "message": f"已写入 {len(applied)} 个单元格。",
    }


def insert_image_at_table_cell(
    db: Session | None,
    session,
    *,
    table_index: int,
    row: int,
    col: int,
    attachment_object_key: str,
    width_pt: float | None = None,
) -> dict[str, Any]:
    from app.services.doc_engine.indexer import insert_image_in_table_cell

    doc_bytes, ws, _doc_key = _load_session_docx(session)
    if not doc_bytes:
        return {"ok": False, "error": "工作区没有打开的标书 DOCX"}
    image_key = (attachment_object_key or "").strip()
    if not image_key:
        return {"ok": False, "error": "请提供 attachment_object_key"}
    try:
        image_bytes = storage.download_bytes(image_key)
    except Exception:
        return {"ok": False, "error": "图片附件不存在或无法读取"}
    data = insert_image_in_table_cell(
        doc_bytes,
        int(table_index),
        int(row),
        int(col),
        image_bytes,
        width_pt=width_pt,
    )
    manifest = _manifest_for_session(db, ws)
    saved = _store_docx(db, session, ws, data, "cell_image")
    ws = dict(session.workspace or {})
    ws, doc_map = _persist_outline_ws(ws, data, manifest)
    session.workspace = ws
    if db is not None:
        db.commit()
    return {
        "ok": True,
        "modified": True,
        "object_key": saved,
        "table_index": int(table_index),
        "row": int(row),
        "col": int(col),
        "outline": compact_outline_for_agent(doc_map),
        "message": "已在表格单元格插入图片。",
    }


def refresh_project_document_map(
    db: Session,
    project,
    docx_bytes: bytes,
    manifest: dict[str, Any] | None = None,
) -> None:
    """materialize/render 后写入 project.fields._document_outline。"""
    stored = merge_outline_into_fields(project.fields or {}, docx_bytes, manifest)
    project.fields = stored
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(project, "fields")
