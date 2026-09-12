"""Agent 可调用的系统查询与检索工具（真实读取数据库状态）。"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy.orm import Session

from app.models import CompanyProfile, ProjectExport, Template, TenderProject


def _fuzzy_score(query: str, text: str) -> float:
    q = (query or "").strip().lower()
    t = (text or "").strip().lower()
    if not q or not t:
        return 0.0
    if q in t:
        return 0.95
    return SequenceMatcher(None, q, t).ratio()


def get_company_summary(db: Session) -> dict[str, Any]:
    c = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not c:
        return {"found": False}
    return {
        "found": True,
        "full_name": c.full_name,
        "short_name": c.short_name,
        "credit_code": c.credit_code,
        "legal_name": c.legal_name,
        "registered_capital": c.registered_capital,
        "phone": c.phone,
        "qual_overview": (c.qual_overview or "")[:800],
        "typical_projects": (c.typical_projects or "")[:500],
    }


def count_templates(db: Session) -> dict[str, Any]:
    total = db.query(Template).count()
    enabled = db.query(Template).filter(Template.enabled.is_(True)).count()
    by_kind: dict[str, int] = {}
    for t in db.query(Template).all():
        k = t.kind or "template"
        by_kind[k] = by_kind.get(k, 0) + 1
    return {
        "total": total,
        "enabled": enabled,
        "by_kind": by_kind,
        "label": "标书模板/脚本",
    }


def count_projects(db: Session) -> dict[str, Any]:
    total = db.query(TenderProject).count()
    draft = db.query(TenderProject).filter(TenderProject.status == "draft").count()
    return {"total": total, "draft": draft}


def list_recent_projects(db: Session, days: int = 7, limit: int = 20) -> list[dict[str, Any]]:
    since = datetime.utcnow() - timedelta(days=max(1, days))
    items = (
        db.query(TenderProject)
        .filter(TenderProject.created_at >= since)
        .order_by(TenderProject.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_project_brief(p, db) for p in items]


def search_projects(db: Session, query: str, limit: int = 8) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    projects = db.query(TenderProject).order_by(TenderProject.updated_at.desc()).limit(80).all()
    scored = []
    for p in projects:
        title = p.title or ""
        fields = p.fields or {}
        blob = f"{title} {fields.get('project_name', '')} {fields.get('tender_no', '')}"
        score = _fuzzy_score(q, blob)
        if score >= 0.35:
            scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [_project_brief(p, db, include_exports=True) for _, p in scored[:limit]]


def search_templates(db: Session, query: str, limit: int = 8) -> list[dict[str, Any]]:
    q = (query or "").strip()
    templates = db.query(Template).order_by(Template.id.desc()).limit(80).all()
    scored = []
    for t in templates:
        score = _fuzzy_score(q, f"{t.name} {t.description or ''}")
        if score >= 0.35:
            scored.append((score, t))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for _, t in scored[:limit]:
        ph = (t.placeholders or {}).get("list") or []
        out.append({
            "id": t.id,
            "name": t.name,
            "kind": t.kind,
            "enabled": bool(t.enabled),
            "placeholder_count": len(ph),
            "created_at": t.created_at.isoformat() if t.created_at else "",
        })
    return out


def _project_brief(p: TenderProject, db: Session, include_exports: bool = False) -> dict[str, Any]:
    item = {
        "id": p.id,
        "title": p.title,
        "status": p.status,
        "current_step": p.current_step,
        "project_name": (p.fields or {}).get("project_name") or "",
        "created_at": p.created_at.isoformat() if p.created_at else "",
        "updated_at": p.updated_at.isoformat() if p.updated_at else "",
        "edit_url": f"/projects/{p.id}/step/{p.current_step or 1}",
    }
    if include_exports:
        exports = (
            db.query(ProjectExport)
            .filter(ProjectExport.project_id == p.id)
            .order_by(ProjectExport.created_at.desc())
            .limit(3)
            .all()
        )
        item["exports"] = [
            {
                "filename": e.filename,
                "created_at": e.created_at.isoformat() if e.created_at else "",
                "download_hint": f"项目 #{p.id} 导出文件 {e.filename}",
            }
            for e in exports
        ]
    return item


def build_system_snapshot(db: Session, workspace: dict | None = None) -> dict[str, Any]:
    ws = workspace or {}
    tpl_stats = count_templates(db)
    proj_stats = count_projects(db)
    company = get_company_summary(db)
    return {
        "company_name": company.get("full_name") or company.get("short_name") or "",
        "template_total": tpl_stats["total"],
        "template_enabled": tpl_stats["enabled"],
        "project_total": proj_stats["total"],
        "project_draft": proj_stats["draft"],
        "workspace_has_doc": bool(ws.get("draft_object_key") or ws.get("template_object_key")),
        "workspace_filename": ws.get("filename") or "",
        "awaiting_file_intent": bool(ws.get("awaiting_file_intent")),
    }


def parse_bulk_replace(text: str) -> tuple[str, str] | None:
    """解析「把 A 全部替换成 B」类指令。"""
    patterns = [
        r"把[「『\"']?(.+?)[」』\"']?全部替换成[「『\"']?(.+?)[」』\"']?$",
        r"将[「『\"']?(.+?)[」』\"']?全部替换为[「『\"']?(.+?)[」』\"']?$",
        r"把[「『\"']?(.+?)[」』\"']?替换成[「『\"']?(.+?)[」』\"']?$",
    ]
    q = text.strip()
    for pat in patterns:
        m = re.search(pat, q)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return None
