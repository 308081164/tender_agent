"""Agent 资质目录扫描：本地路径白名单、文件读取、企业档案/资质落库、缺口清单。"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import DATA_DIR, INSTALL_DIR, IS_DESKTOP, ROOT
from app.models import CompanyProfile, FieldDef, Qualification
from app.services import storage
from app.services.field_defaults import FIELD_COMPANY_MAP, resolve_company_field
from app.services.ocr_service import extract_text_from_file
from app.services.qual_extract import analyze_qualification_file

SCAN_EXTENSIONS = frozenset({
    "pdf", "docx", "txt", "jpg", "jpeg", "png", "bmp", "gif", "webp", "tif", "tiff",
})
MAX_FOLDER_FILES = 40
MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_TOTAL_BYTES = 80 * 1024 * 1024

# 企业档案列：自动写入前若已有不同值则仅建议、不覆盖
SENSITIVE_COMPANY_COLUMNS = frozenset({
    "legal_id_no",
    "bank_account",
    "credit_code",
})

COMPANY_ONBOARDING: list[tuple[str, str]] = [
    ("full_name", "企业全称"),
    ("short_name", "简称"),
    ("credit_code", "统一社会信用代码"),
    ("register_address", "注册地址"),
    ("office_address", "办公地址"),
    ("legal_name", "法定代表人"),
    ("registered_capital", "注册资本"),
    ("phone", "联系电话"),
    ("bank_name", "开户行"),
    ("bank_account", "银行账号"),
    ("qual_overview", "资质概述"),
]

COMPANY_EXTRACT_PROMPT = """你是企业档案识别助手。根据资质文件夹内材料提取的文本，输出 JSON 对象。
键为企业档案字段（仅包含有依据的字段，无则省略）：
full_name, short_name, credit_code, register_address, office_address,
legal_name, legal_gender, legal_age, legal_title, legal_id_no,
registered_capital, founded_date, phone, fax, email, website, postcode,
bank_name, bank_account, intro, business_scope, qual_overview, typical_projects

只输出 JSON，不要 markdown。"""


class PathNotAllowedError(ValueError):
    pass


def _windows_user_dirs() -> list[Path]:
    home = Path.home()
    dirs = [home, home / "Desktop", home / "Documents", home / "Downloads"]
    if os.name == "nt":
        for env_key in ("USERPROFILE", "HOMEDRIVE", "HOMEPATH"):
            raw = os.environ.get(env_key, "").strip()
            if raw:
                try:
                    dirs.append(Path(raw).resolve())
                except OSError:
                    pass
        one_drive = os.environ.get("OneDrive", "").strip()
        if one_drive:
            try:
                dirs.append(Path(one_drive).resolve())
            except OSError:
                pass
    return dirs


def allowed_path_prefixes() -> list[Path]:
    prefixes: list[Path] = []
    for p in (
        DATA_DIR,
        INSTALL_DIR,
        ROOT,
        Path("/tmp"),
        Path("/workspace"),
    ):
        try:
            if p.exists():
                prefixes.append(p.resolve())
        except OSError:
            continue
    prefixes.extend(_windows_user_dirs())
    customer = os.environ.get("TENDER_CUSTOMER_DATA", "").strip()
    if customer:
        try:
            cp = Path(customer).resolve()
            if cp.exists():
                prefixes.append(cp)
        except OSError:
            pass
    from app.config import get_settings

    settings = get_settings()
    cd = (settings.customer_data_dir or "").strip()
    if cd:
        try:
            cp = Path(cd).resolve()
            if cp.exists():
                prefixes.append(cp)
        except OSError:
            pass
    # 去重
    seen: set[str] = set()
    out: list[Path] = []
    for p in prefixes:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def normalize_folder_path(raw: str) -> Path:
    text = (raw or "").strip().strip('"').strip("'").strip("「」")
    if not text:
        raise PathNotAllowedError("路径不能为空")
    if ".." in text.replace("\\", "/"):
        raise PathNotAllowedError("路径不允许包含 ..")
    if text.startswith("\\\\") or text.startswith("//"):
        raise PathNotAllowedError("不支持网络路径")
    try:
        path = Path(text).expanduser().resolve()
    except OSError as err:
        raise PathNotAllowedError(f"无效路径：{err}") from err
    if not path.is_dir():
        raise PathNotAllowedError("路径必须是已存在的文件夹")
    prefixes = allowed_path_prefixes()
    if IS_DESKTOP or os.environ.get("TENDER_ALLOW_LOCAL_PATHS", "").strip() in ("1", "true"):
        pass  # 桌面模式仍要求前缀白名单，前缀已含用户目录
    elif not prefixes:
        raise PathNotAllowedError("当前环境未配置允许的路径前缀")
    for prefix in prefixes:
        try:
            path.relative_to(prefix)
            return path
        except ValueError:
            continue
    raise PathNotAllowedError(
        "路径不在允许范围内。请使用本机桌面、文档、下载目录或安装目录下的文件夹。"
    )


def extract_folder_path_from_text(text: str) -> str | None:
    q = (text or "").strip()
    if not q:
        return None
    m = re.search(r"[「『\"']([^」』\"']+)[」』\"']", q)
    if m and ("/" in m.group(1) or "\\" in m.group(1) or re.match(r"[A-Za-z]:", m.group(1))):
        return m.group(1).strip()
    m2 = re.search(r"([A-Za-z]:\\[^\s\"'，,；;]+)", q)
    if m2:
        return m2.group(1).rstrip("\\")
    m3 = re.search(r"(/(?:tmp|workspace|home|Users)[^\s\"'，,；;]*)", q)
    if m3:
        return m3.group(1).rstrip("/")
    return None


def is_qual_folder_intent(text: str) -> bool:
    q = (text or "").strip()
    if not q:
        return False
    keys = (
        "资质文件夹", "资质目录", "资质材料", "导入资质", "扫描文件夹", "扫描目录",
        "读取文件夹", "企业档案导入", "落库", "资质包",
    )
    if any(k in q for k in keys) and extract_folder_path_from_text(q):
        return True
    if any(k in q for k in keys) and re.search(r"[A-Za-z]:\\|/", q):
        return True
    return False


def scan_qual_folder(folder: Path | str) -> dict[str, Any]:
    root = normalize_folder_path(str(folder))
    files: list[dict[str, Any]] = []
    total_bytes = 0
    skipped: list[dict[str, str]] = []

    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if len(files) >= MAX_FOLDER_FILES:
                skipped.append({"file": name, "reason": "超过单次扫描文件数上限"})
                continue
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in SCAN_EXTENSIONS:
                continue
            full = Path(dirpath) / name
            try:
                stat = full.stat()
            except OSError:
                skipped.append({"file": name, "reason": "无法读取文件信息"})
                continue
            if stat.st_size > MAX_FILE_BYTES:
                skipped.append({"file": name, "reason": "文件过大"})
                continue
            if total_bytes + stat.st_size > MAX_TOTAL_BYTES:
                skipped.append({"file": name, "reason": "超过总大小上限"})
                continue
            try:
                rel = str(full.relative_to(root))
            except ValueError:
                rel = name
            files.append({
                "path": str(full),
                "relative_path": rel,
                "name": name,
                "extension": ext,
                "size_bytes": stat.st_size,
            })
            total_bytes += stat.st_size

    return {
        "folder": str(root),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
        "skipped": skipped,
        "limits": {
            "max_files": MAX_FOLDER_FILES,
            "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_BYTES,
        },
    }


def read_document_file(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在：{path}")
    parent = p.parent
    normalize_folder_path(str(parent))
    data = p.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("文件超过大小上限")
    ext = p.suffix.lstrip(".").lower()
    text = extract_text_from_file(data, ext, name=p.name)
    if ext == "txt" and not text.strip():
        try:
            text = data.decode("utf-8", errors="ignore")[:8000]
        except Exception:
            text = ""
    return {
        "path": str(p.resolve()),
        "name": p.name,
        "extension": ext,
        "size_bytes": len(data),
        "text_preview": (text or "")[:500],
        "data": data,
    }


def _parse_company_json(raw: str) -> dict[str, str]:
    text = (raw or "").strip()
    if not text:
        return {}
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    allowed = {k for k, _ in COMPANY_ONBOARDING} | {
        "legal_gender", "legal_age", "legal_title", "fax", "email", "website", "postcode",
        "intro", "business_scope", "typical_projects", "recent_revenue", "related_companies",
    }
    out: dict[str, str] = {}
    for k, v in data.items():
        if k not in allowed:
            continue
        if v is None:
            continue
        s = str(v).strip()
        if s:
            out[k] = s
    return out


async def extract_company_patch_from_texts(
    texts: list[str],
    *,
    db: Session | None = None,
) -> dict[str, str]:
    combined = "\n\n---\n\n".join(t[:4000] for t in texts if t.strip())[:12000]
    if not combined.strip():
        return {}
    from app.services import ai

    raw = await ai.chat_completion([
        {"role": "system", "content": COMPANY_EXTRACT_PROMPT},
        {"role": "user", "content": f"材料文本：\n{combined}"},
    ], db=db)
    return _parse_company_json(raw or "")


def apply_company_field_patch(
    db: Session,
    patch: dict[str, Any],
    *,
    force_sensitive: bool = False,
) -> dict[str, Any]:
    c = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not c:
        c = CompanyProfile(id=1)
        db.add(c)
        db.flush()

    applied: list[dict[str, str]] = []
    suggestions: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for key, raw_val in (patch or {}).items():
        if key not in CompanyProfile.__table__.columns.keys():
            skipped.append({"key": key, "reason": "unknown_column"})
            continue
        val = str(raw_val or "").strip()
        if not val:
            continue
        current = str(getattr(c, key, "") or "").strip()
        if key in SENSITIVE_COMPANY_COLUMNS:
            if current and current != val and not force_sensitive:
                suggestions.append({
                    "key": key,
                    "label": next((lbl for k, lbl in COMPANY_ONBOARDING if k == key), key),
                    "current": current[:80],
                    "suggested": val[:80],
                })
                continue
        if current == val:
            skipped.append({"key": key, "reason": "unchanged"})
            continue
        setattr(c, key, val)
        applied.append({"key": key, "value": val[:120]})

    c.updated_at = datetime.utcnow()
    db.flush()
    return {"applied": applied, "suggestions": suggestions, "skipped": skipped}


def apply_qual_record(
    db: Session,
    file_info: dict[str, Any],
    analyzed: dict[str, Any],
    data: bytes,
) -> dict[str, Any]:
    category = analyzed.get("category") or "其他"
    name = analyzed.get("name") or file_info.get("name") or "资质材料"
    fname = file_info.get("name") or "file.bin"
    ext = (analyzed.get("file_type") or file_info.get("extension") or "bin").lower()
    key = f"qualifications/{category}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{fname}"
    storage.upload_bytes(key, data, "application/octet-stream")

    def _parse_d(s: str | None) -> date | None:
        if not s:
            return None
        try:
            return date.fromisoformat(str(s)[:10])
        except ValueError:
            return None

    q = Qualification(
        category=category,
        name=name[:200],
        issuer=str(analyzed.get("issuer") or "")[:200],
        file_type=ext,
        file_name=fname[:300],
        object_key=key,
        keywords=str(analyzed.get("keywords") or "")[:500],
        section_hint=str(analyzed.get("section_hint") or "")[:200],
        valid_from=_parse_d(analyzed.get("valid_from")),
        valid_to=_parse_d(analyzed.get("valid_to")),
        is_long_term=bool(analyzed.get("is_long_term")),
        ocr_text=str(analyzed.get("ocr_text") or "")[:8000],
    )
    db.add(q)
    db.flush()
    return {
        "id": q.id,
        "name": q.name,
        "category": q.category,
        "file_name": q.file_name,
        "admin_url": f"/admin/qualifications?focus={q.id}",
    }


def _company_column_empty(c: CompanyProfile, col: str) -> bool:
    return not str(getattr(c, col, "") or "").strip()


def get_onboarding_gaps(db: Session) -> dict[str, Any]:
    c = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    gaps: list[dict[str, Any]] = []

    for key, label in COMPANY_ONBOARDING:
        if not c or _company_column_empty(c, key):
            gaps.append({
                "kind": "company",
                "key": key,
                "label": label,
                "status": "empty",
                "url": f"/admin/company?focus={key}",
            })

    for fd in db.query(FieldDef).order_by(FieldDef.sort_order.asc()).all():
        cf = resolve_company_field(fd) or FIELD_COMPANY_MAP.get(fd.key, "")
        if not cf or not c:
            continue
        if _company_column_empty(c, cf):
            gaps.append({
                "kind": "field_def",
                "key": fd.key,
                "label": f"字段默认值：{fd.name}",
                "status": "empty",
                "url": f"/admin/fields?focus={fd.key}",
            })

    verify_pending: list[dict[str, Any]] = []
    if c:
        for key, label in COMPANY_ONBOARDING:
            if key in SENSITIVE_COMPANY_COLUMNS and not _company_column_empty(c, key):
                verify_pending.append({
                    "kind": "verify",
                    "key": key,
                    "label": label,
                    "status": "needs_verify",
                    "url": f"/admin/company?focus={key}",
                })

    disclaimer = (
        "⚠️ **重要**：以上内容由 AI 从文件夹自动识别并写入系统，可能存在错漏。"
        "**强烈建议您逐项打开企业管理页人工核对**，确认无误后再用于投标导出。"
    )

    return {
        "gaps": gaps,
        "verify_recommended": verify_pending,
        "gap_count": len(gaps),
        "verify_count": len(verify_pending),
        "disclaimer": disclaimer,
        "admin_links": [
            {"label": "企业档案", "url": "/admin/company", "primary": True},
            {"label": "字段管理", "url": "/admin/fields"},
            {"label": "资质库", "url": "/admin/qualifications"},
        ],
    }


async def import_qual_folder_pipeline(
    db: Session,
    folder: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    scan = scan_qual_folder(folder)
    qual_created: list[dict] = []
    errors: list[dict] = []
    texts_for_company: list[str] = []

    for fi in scan["files"]:
        try:
            doc = read_document_file(fi["path"])
            if dry_run:
                qual_created.append({"name": fi["name"], "dry_run": True})
                continue
            analyzed = await analyze_qualification_file(
                doc["data"], fi["name"], fi["extension"], db=db,
            )
            rec = apply_qual_record(db, fi, analyzed, doc["data"])
            qual_created.append(rec)
            if analyzed.get("ocr_text"):
                texts_for_company.append(analyzed["ocr_text"])
            elif doc.get("text_preview"):
                texts_for_company.append(doc["text_preview"])
        except Exception as err:
            errors.append({"file": fi.get("name"), "error": str(err)[:200]})

    company_result: dict[str, Any] = {"applied": [], "suggestions": []}
    if not dry_run and texts_for_company:
        patch = await extract_company_patch_from_texts(texts_for_company, db=db)
        if patch:
            company_result = apply_company_field_patch(db, patch)

    if not dry_run:
        db.commit()

    gaps = get_onboarding_gaps(db)
    return {
        "scan": {
            "folder": scan["folder"],
            "file_count": scan["file_count"],
            "skipped": scan.get("skipped") or [],
        },
        "qualifications_created": qual_created,
        "company_patch": company_result,
        "errors": errors,
        "onboarding": gaps,
    }
