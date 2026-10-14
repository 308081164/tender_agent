"""文档 Agent 能力 1–9：备忘、旁路提问、招标对照、选区锚点、审查点修。

这些函数不访问公网，也不启动 OnlyOffice。对话与工具环只调用这里的判定和落库。
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import TenderProject

MAX_TOOL_STEPS = 8
ANCHOR_MISSING = "请先选中位置"

_DECISION_PREFIX = re.compile(r"^(记住|决定|备忘)\s*[:：]\s*(.+)$")
_DECISION_FRAMES = [
    re.compile(r"以[^。！？?\n]{1,48}为准"),
    re.compile(r"(?:这章|本章|这一章)[^。！？?\n]{0,16}不写[^。！？?\n]{0,24}"),
    re.compile(r"先不写[^。！？?\n]{0,24}"),
    re.compile(r"一律[^。！？?\n]{1,40}"),
    re.compile(r"统一(?:按|用|采用)[^。！？?\n]{1,40}"),
    re.compile(r"口径(?:是|为|用)[^。！？?\n]{1,40}"),
    re.compile(r"就按[^。！？?\n]{1,40}"),
    re.compile(r"以后都[^。！？?\n]{1,40}"),
    re.compile(r"不要(?:再)?写[^。！？?\n]{1,24}"),
    re.compile(r"我们决定[^。！？?\n]{1,48}"),
    re.compile(r"就这么定[:：]?[^。！？?\n]{0,48}"),
    re.compile(r"报价[^。！？?\n]{0,16}(?:按|以|用)[^。！？?\n]{1,32}"),
    re.compile(r"人员[^。！？?\n]{0,20}(?:按|不写|先不|就按)[^。！？?\n]{0,32}"),
]
_DURATION_RE = re.compile(r"(\d+\s*(?:个)?(?:日历)?(?:天|日|个月|月|年))")
_DATE_RE = re.compile(r"\d{4}\s*[-年/.]\s*\d{1,2}\s*[-月/.]\s*\d{1,2}\s*日?")

_READONLY_RE = re.compile(
    r"(联网|网上查|搜索一下|查一下公开|公开资料|公司全称|企业名称|企业档案|"
    r"有哪些资质|查(一下)?(企业|公司|资质|人员|业绩)|进度|到哪了|进行到哪|"
    r"现在哪一步|流程到哪|读(一下)?文件|看看文件|打开文件|文件内容|预览状态|预览好了)",
)
_MUTATING_RE = re.compile(
    r"(确认生成|确认导入|开始扫描|创建项目|新建标书|帮我写标书|导入资质|"
    r"写入文件|覆盖文件|修改字段|替换全文|确认映射)",
)
_FIX_ISSUE_RE = re.compile(r"(改这一条|修改这一条|只改这条|处理这一条)")


def tool_loop_default_on() -> bool:
    """未设置 AGENT_TOOL_LOOP 时工具环默认开启。"""
    return True


def interrupted_answer(partial: str, reason: str) -> str:
    """流式失败时保留已流出的文字，并附上错误原因。"""
    why = (reason or "未知错误").strip() or "未知错误"
    note = f"（回复中断：{why}）"
    text = partial or ""
    if not text.strip():
        return note
    if why in text:
        return text
    return text.rstrip() + "\n\n" + note


def iter_text_chunks(text: str, size: int = 24):
    body = text or ""
    if not body:
        return
    step = max(1, size)
    for i in range(0, len(body), step):
        yield body[i : i + step]


def public_tool_trace(tool_log: list[dict] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in tool_log or []:
        result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
        ok = True
        if "ok" in result:
            ok = bool(result.get("ok"))
        rows.append({"tool": str(entry.get("tool") or ""), "ok": ok})
    return [row for row in rows if row["tool"]]


def trace_sentence(trace: list[dict] | None) -> str:
    names = [str(item.get("tool") or "") for item in (trace or []) if item.get("tool")]
    if not names:
        return ""
    return "调用了工具：" + "、".join(names)


def extract_decision(text: str) -> str | None:
    """从陈述句里抽出决定。问句整句跳过，不靠单一「以…为准」。"""
    raw = (text or "").strip()
    if not raw or len(raw) > 800:
        return None
    if not re.search(r"[?？]", raw):
        prefixed = _DECISION_PREFIX.match(raw)
        if prefixed and prefixed.group(2).strip():
            return prefixed.group(2).strip()[:240]
    clauses = re.split(r"[。！\n；;]", raw)
    for clause in clauses:
        bit = clause.strip(" \t，,")
        if not bit or re.search(r"[?？]", bit):
            continue
        for frame in _DECISION_FRAMES:
            found = frame.search(bit)
            if found:
                return bit[:240]
    return None


def project_memos(fields: dict | None) -> list[dict[str, Any]]:
    rows = []
    for item in (fields or {}).get("_agent_memos") or []:
        if isinstance(item, dict) and (item.get("text") or "").strip():
            rows.append({
                "id": str(item.get("id") or ""),
                "text": str(item.get("text")).strip(),
                "created_at": str(item.get("created_at") or ""),
            })
    return rows


def remember_decision(project: TenderProject, text: str) -> dict[str, Any] | None:
    """写入标书备忘。不改动已填字段，也不把它们标成待核实。"""
    decision = extract_decision(text)
    if not decision:
        return None
    fields = dict(project.fields or {})
    memos = project_memos(fields)
    for item in memos:
        if item["text"] == decision:
            return item
    memo = {
        "id": uuid.uuid4().hex[:12],
        "text": decision,
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    memos.append(memo)
    fields["_agent_memos"] = memos[-40:]
    project.fields = fields
    flag_modified(project, "fields")
    return memo


def delete_memo(project: TenderProject, memo_id: str) -> bool:
    fields = dict(project.fields or {})
    memos = project_memos(fields)
    kept = [item for item in memos if item["id"] != str(memo_id)]
    if len(kept) == len(memos):
        return False
    fields["_agent_memos"] = kept
    project.fields = fields
    flag_modified(project, "fields")
    return True


def memo_prompt_block(fields: dict | None) -> str:
    memos = project_memos(fields)
    if not memos:
        return ""
    lines = "\n".join(f"- {item['text']}" for item in memos)
    return "项目备忘（用户已决定，下一轮必须遵守）：\n" + lines


def side_question_kind(text: str, context: dict | None = None) -> str:
    """readonly：不改当前流程；mutating：会打断卡片流程；other：交给原流程提示。"""
    ctx = context or {}
    if ctx.get("web_search"):
        return "readonly"
    q = (text or "").strip()
    if not q:
        return "other"
    if _READONLY_RE.search(q):
        return "readonly"
    if _MUTATING_RE.search(q):
        return "mutating"
    return "other"


def mutating_flow_reply() -> str:
    return "这会改变当前进行中的流程。请在卡片上确认，或发送「取消」。"


def progress_reply(workspace: dict | None, project: TenderProject | None = None) -> str:
    ws = workspace or {}
    pa = ws.get("pending_action") if isinstance(ws.get("pending_action"), dict) else {}
    labels = {
        ("template_create", "confirm_mapping"): "正在确认模板占位符映射",
        ("project_create", "select_template"): "正在选择标书模板",
        ("project_create", "collect_fields"): "正在收集项目字段",
        ("project_create", "collect_requirements"): "正在收集编写要求",
        ("project_create", "revise_document"): "正在修订已生成的标书",
        ("qual_folder_import", "confirm_scan"): "正在等待确认资质文件夹导入",
    }
    where = labels.get((pa.get("flow"), pa.get("stage")), "有一张卡片任务还没完成")
    extra = ""
    if project is not None:
        extra = f"标书「{project.title}」当前第 {project.current_step or 1} 步。"
    return f"当前进度：{where}。{extra}只读问题可以继续问；要改流程请在卡片上确认，或发送「取消」。"


def parse_tender_text(text: str) -> dict[str, Any]:
    """从招标正文抽出评分点、废标项、工期、资质和关键日期。"""
    scoring: list[str] = []
    disqualification: list[str] = []
    qualifications: list[str] = []
    dates: list[str] = []
    duration = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.search(r"评分|得分|分值", line):
            scoring.append(line[:240])
        if re.search(r"废标|否决投标|无效投标|按废标", line):
            disqualification.append(line[:240])
        if re.search(r"资质", line):
            qualifications.append(line[:240])
        if not duration and "工期" in line:
            found = _DURATION_RE.search(line)
            if found:
                duration = re.sub(r"\s+", "", found.group(1))
        for item in _DATE_RE.findall(line):
            cleaned = re.sub(r"\s+", "", item)
            if cleaned not in dates:
                dates.append(cleaned)
    return {
        "scoring_points": scoring[:30],
        "disqualification": disqualification[:30],
        "duration": duration,
        "qualifications": qualifications[:30],
        "key_dates": dates[:20],
        "excerpt": (text or "").strip()[:4000],
    }


def store_tender_record(project: TenderProject, parsed: dict[str, Any], *, name: str, object_key: str = "") -> dict[str, Any]:
    fields = dict(project.fields or {})
    record = {
        "name": name[:180],
        "object_key": object_key,
        "scoring_points": list(parsed.get("scoring_points") or []),
        "disqualification": list(parsed.get("disqualification") or []),
        "duration": parsed.get("duration") or "",
        "qualifications": list(parsed.get("qualifications") or []),
        "key_dates": list(parsed.get("key_dates") or []),
        "excerpt": (parsed.get("excerpt") or "")[:4000],
    }
    fields["_tender"] = record
    project.fields = fields
    flag_modified(project, "fields")
    return record


def tender_record(fields: dict | None) -> dict[str, Any]:
    raw = (fields or {}).get("_tender")
    return dict(raw) if isinstance(raw, dict) else {}


def tender_prompt_block(fields: dict | None) -> str:
    tender = tender_record(fields)
    if not tender:
        return ""
    parts = ["招标文件摘录（写作时用 check_against_tender 对照，不要只在导出时看）："]
    if tender.get("duration"):
        parts.append(f"- 工期：{tender['duration']}")
    for label, key in (
        ("评分点", "scoring_points"),
        ("废标项", "disqualification"),
        ("资质", "qualifications"),
        ("关键日期", "key_dates"),
    ):
        rows = tender.get(key) or []
        if rows:
            parts.append(f"- {label}：" + "；".join(str(x) for x in rows[:6]))
    return "\n".join(parts)


def _duration_in(text: str) -> str:
    if "工期" not in (text or ""):
        return ""
    found = _DURATION_RE.search(text or "")
    if not found:
        return ""
    return re.sub(r"\s+", "", found.group(1))


def check_against_tender(draft: str, tender: dict[str, Any] | None) -> dict[str, Any]:
    """写作过程中对照招标摘录。没有招标文件时明确说明，不假装通过。"""
    record = tender or {}
    if not record:
        return {"ok": False, "error": "项目未挂招标文件", "conflicts": []}
    conflicts: list[dict[str, str]] = []
    expected = re.sub(r"\s+", "", str(record.get("duration") or ""))
    actual = _duration_in(draft or "")
    if expected and actual and expected != actual:
        conflicts.append({
            "kind": "duration",
            "tender": expected,
            "draft": actual,
            "message": f"工期与招标文件冲突：文稿为 {actual}，招标文件为 {expected}",
        })
    for rule in record.get("disqualification") or []:
        rule_text = str(rule)
        banned = re.search(r"不得([^，。；]{2,24})", rule_text)
        if banned and banned.group(1) in (draft or ""):
            conflicts.append({
                "kind": "disqualification",
                "tender": rule_text[:180],
                "draft": banned.group(1),
                "message": f"可能触发废标项：文稿出现「{banned.group(1)}」",
            })
    for point in record.get("scoring_points") or []:
        token = _tender_token(str(point), drop=r"评分办法|评分标准|评分点|得分|分值|\d+\s*分")
        if token and token not in (draft or ""):
            conflicts.append({
                "kind": "scoring",
                "tender": str(point)[:180],
                "draft": "",
                "message": f"文稿未覆盖评分点：{token}",
            })
    for qual in record.get("qualifications") or []:
        token = _tender_token(str(qual), drop=r"资质要求|投标人须具备|须具备|资质")
        if token and token not in (draft or ""):
            conflicts.append({
                "kind": "qualification",
                "tender": str(qual)[:180],
                "draft": "",
                "message": f"文稿未体现招标资质：{token}",
            })
    draft_dates = [re.sub(r"\s+", "", item) for item in _DATE_RE.findall(draft or "")]
    for raw_date in record.get("key_dates") or []:
        expected = re.sub(r"\s+", "", str(raw_date))
        if not expected or expected in (draft or ""):
            continue
        if not re.search(r"截止|开标|日期|时间", draft or ""):
            continue
        if any(item != expected for item in draft_dates):
            conflicts.append({
                "kind": "date",
                "tender": expected,
                "draft": next((item for item in draft_dates if item != expected), ""),
                "message": f"关键日期与招标文件不一致：文稿为 {draft_dates[0] if draft_dates else '未写'}，招标文件为 {expected}",
            })
    return {"ok": not conflicts, "conflicts": conflicts, "error": ""}


def _tender_token(line: str, *, drop: str) -> str:
    text = re.sub(drop, "", line or "")
    text = re.sub(r"[：:，,。；;\s]", "", text)
    text = text.strip()
    if len(text) < 4:
        return ""
    return text[:40]


def _optional_index(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_document_anchor(context: dict | None, arguments: dict | None = None) -> dict[str, Any]:
    """选中文字、段落索引或章节/块 id 都算锚点。缺省不回落到段落 0。"""
    ctx = context or {}
    args = arguments or {}
    nested = ctx.get("anchor") if isinstance(ctx.get("anchor"), dict) else {}
    mentions = normalize_mentions(ctx.get("mentions"))
    section_mention = next((item for item in mentions if item["kind"] == "section"), None)
    file_mention = next((item for item in mentions if item["kind"] == "file" and item.get("path")), None)
    selected = str(
        args.get("selected_text")
        or ctx.get("selected_text")
        or nested.get("selected_text")
        or ""
    ).strip()
    block_id = str(
        args.get("block_id")
        or args.get("section_id")
        or ctx.get("block_id")
        or ctx.get("section_id")
        or nested.get("block_id")
        or nested.get("section_id")
        or ""
    ).strip()
    if not selected and not block_id and section_mention:
        block_id = section_mention.get("section_id") or ""
        selected = section_mention.get("label") or ""
    index = _optional_index(args.get("paragraph_index"))
    if index is None:
        index = _optional_index(ctx.get("paragraph_index", nested.get("paragraph_index")))
    if index is None and block_id:
        matched = re.search(r"(?:^|:)(\d+)$", block_id)
        if matched and (block_id.startswith("section:") or block_id.startswith("p:") or block_id.startswith("block:")):
            index = int(matched.group(1))
    path = str(args.get("path") or ctx.get("mention_path") or "").strip()
    if not path and file_mention and not selected and not block_id and index is None:
        path = file_mention.get("path") or ""
    if not selected and not block_id and index is None and not path:
        return {"ok": False, "message": ANCHOR_MISSING}
    return {
        "ok": True,
        "message": "",
        "selected_text": selected,
        "block_id": block_id,
        "paragraph_index": index,
        "path": path,
    }


def anchor_can_insert(anchor: dict[str, Any]) -> bool:
    return bool(anchor.get("ok") and anchor.get("paragraph_index") is not None)


def normalize_mentions(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw[:16]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("name") or "").strip()
        if not label:
            continue
        kind = "section" if str(item.get("kind") or "") == "section" else "file"
        out.append({
            "kind": kind,
            "label": label[:180],
            "path": str(item.get("path") or "")[:300],
            "section_id": str(item.get("section_id") or item.get("id") or "")[:80],
        })
    return out


def mention_prompt_block(mentions: list[dict] | None) -> str:
    rows = normalize_mentions(mentions)
    if not rows:
        return ""
    lines = []
    for item in rows:
        if item["kind"] == "section":
            lines.append(f"- 章节 {item['label']}（{item['section_id'] or '未编号'}）")
        else:
            lines.append(f"- 文件 {item['label']}（{item['path'] or item['label']}）")
    return "用户本轮 @ 引用（必须纳入上下文）：\n" + "\n".join(lines)


def _walk_workspace_files(root, limit: int = 80) -> list[str]:
    from pathlib import Path

    base = Path(root).resolve()
    found: list[str] = []
    if not base.is_dir():
        return found
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if any(part.startswith(".") for part in path.relative_to(base).parts):
            continue
        found.append(path.relative_to(base).as_posix())
        if len(found) >= limit:
            break
    return found


def mention_candidates(db: Session, session, query: str = "") -> list[dict[str, str]]:
    """工作区文件 + 招标/标书章节。"""
    needle = (query or "").strip().lower()
    items: list[dict[str, str]] = []

    def keep(label: str) -> bool:
        return not needle or needle in label.lower()

    try:
        from app.services.agent_workspace import resolve_session_workspace_root

        root = resolve_session_workspace_root(db, session)
        for path in _walk_workspace_files(root):
            label = path.rsplit("/", 1)[-1]
            if keep(label) or keep(path):
                items.append({
                    "kind": "file",
                    "label": label,
                    "path": path,
                    "section_id": "",
                })
    except Exception:
        pass

    ws = getattr(session, "workspace", None) or {}
    doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
    if doc_key:
        try:
            from app.services import storage
            from app.services.docx_ooxml import paragraphs as docx_paragraphs

            for index, line in enumerate(docx_paragraphs(storage.download_bytes(doc_key))[:40]):
                label = (line or "").strip()
                if len(label) < 2 or not keep(label):
                    continue
                items.append({
                    "kind": "section",
                    "label": label[:80],
                    "path": "",
                    "section_id": f"p:{index}",
                })
        except Exception:
            pass
    pid = ws.get("project_id")
    project = None
    if pid:
        project = db.query(TenderProject).filter(TenderProject.id == int(pid)).first()
    if project is not None:
        tender = tender_record(project.fields)
        for index, line in enumerate(tender.get("scoring_points") or []):
            label = str(line)[:80]
            if keep(label):
                items.append({
                    "kind": "section",
                    "label": label,
                    "path": "",
                    "section_id": f"tender-score:{index}",
                })
        chapters = project.chapters or {}
        for key, value in chapters.items():
            if not key or str(key).startswith("_"):
                continue
            label = str(key)
            if keep(label):
                items.append({
                    "kind": "section",
                    "label": label,
                    "path": "",
                    "section_id": f"chapter:{label}",
                })
            if isinstance(value, dict):
                title = str(value.get("title") or "").strip()
                if title and title != label and keep(title):
                    items.append({
                        "kind": "section",
                        "label": title,
                        "path": "",
                        "section_id": f"chapter:{label}",
                    })
    return items[:40]


def _quoted_excerpt(message: str) -> str:
    matched = re.search(r"[「『\"](.+?)[」』\"]", message or "")
    return matched.group(1).strip() if matched else ""


def stamp_review_issues(review: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(review or {})
    seq = 1
    for bucket in ("issues", "warnings"):
        stamped = []
        for item in data.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            if not row.get("id"):
                row["id"] = f"rv-{seq}"
            seq += 1
            if not row.get("excerpt"):
                excerpt = _quoted_excerpt(str(row.get("message") or ""))
                if excerpt:
                    row["excerpt"] = excerpt
            stamped.append(row)
        data[bucket] = stamped
    return data


def iter_review_issues(review: dict[str, Any] | None):
    data = review or {}
    for bucket in ("issues", "warnings"):
        for item in data.get(bucket) or []:
            if isinstance(item, dict):
                yield bucket, item


def unresolved_issues(review: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = []
    for _bucket, item in iter_review_issues(review):
        if not item.get("resolved"):
            rows.append(item)
    return rows


def collect_document_text(project: TenderProject) -> str:
    chapters = project.chapters or {}
    parts: list[str] = []
    plain = chapters.get("_plain")
    if isinstance(plain, str) and plain.strip():
        parts.append(plain)
    for key, value in chapters.items():
        if str(key).startswith("_"):
            continue
        if isinstance(value, dict):
            content = value.get("content") or ""
            if content:
                parts.append(str(content))
        elif isinstance(value, str) and value.strip():
            parts.append(value)
    return "\n".join(parts)


def _replace_excerpt(text: str, excerpt: str, replacement: str) -> str:
    if excerpt and excerpt in text:
        return text.replace(excerpt, replacement, 1)
    return text


def _write_document_text(project: TenderProject, excerpt: str, replacement: str) -> None:
    chapters = dict(project.chapters or {})
    wrote = False
    plain = chapters.get("_plain")
    if isinstance(plain, str) and excerpt in plain:
        chapters["_plain"] = plain.replace(excerpt, replacement, 1)
        wrote = True
    for key, value in list(chapters.items()):
        if str(key).startswith("_") or not isinstance(value, dict):
            continue
        content = str(value.get("content") or "")
        if excerpt in content:
            updated = dict(value)
            updated["content"] = content.replace(excerpt, replacement, 1)
            chapters[key] = updated
            wrote = True
    if not wrote:
        full = collect_document_text(project)
        chapters["_plain"] = full.replace(excerpt, replacement, 1)
    project.chapters = chapters
    flag_modified(project, "chapters")


def highlight_texts_for_review(review: dict[str, Any] | None) -> list[str]:
    texts: list[str] = []
    for item in unresolved_issues(review):
        excerpt = str(item.get("excerpt") or "").strip()
        if len(excerpt) >= 2:
            texts.append(excerpt)
    return texts[:12]


def rereview_issue_text(issue: dict[str, Any], document_text: str) -> dict[str, Any]:
    """对照更新后的文档正文复审这一条，不看修改前的章节缓存。"""
    excerpt = str(issue.get("excerpt") or "").strip()
    suggestion = str(issue.get("suggestion") or "").strip()
    body = document_text or ""
    excerpt_gone = bool(excerpt) and excerpt not in body
    suggestion_present = bool(suggestion) and suggestion in body
    return {
        "issue_id": issue.get("id"),
        "ok": excerpt_gone and suggestion_present,
        "excerpt_gone": excerpt_gone,
        "suggestion_present": suggestion_present,
        "checked_on": "document",
    }


def fix_review_issue(
    project: TenderProject,
    issue_id: str,
    docx_bytes: bytes | None = None,
) -> dict[str, Any]:
    """只改指定审查问题，写入打开的 docx，再按更新后的文档复审这一条。"""
    stored = dict((project.checklist_result or {}).get("doc_review") or {})
    review = stamp_review_issues(stored)
    target = None
    bucket_name = ""
    for bucket, item in iter_review_issues(review):
        if str(item.get("id")) == str(issue_id):
            target = item
            bucket_name = bucket
            break
    if target is None:
        return {"ok": False, "error": "没有这一条审查问题", "highlight_texts": highlight_texts_for_review(review)}

    excerpt = str(target.get("excerpt") or _quoted_excerpt(str(target.get("message") or ""))).strip()
    suggestion = str(target.get("suggestion") or "").strip()
    if not suggestion and target.get("field"):
        suggestion = str((project.fields or {}).get(target["field"]) or "").strip()
    if not excerpt or not suggestion:
        return {
            "ok": False,
            "error": "这一条没有可替换的原文和建议，无法只改这一处",
            "issue_id": issue_id,
            "highlight_texts": highlight_texts_for_review(review),
        }
    if excerpt == suggestion:
        return {
            "ok": False,
            "error": "建议与原文相同，没有可修改的内容",
            "issue_id": issue_id,
            "highlight_texts": highlight_texts_for_review(review),
        }

    from app.services.docx_ooxml import build_docx, plain_text, replace_text

    chapter_text = collect_document_text(project)
    source = docx_bytes
    if source is None and excerpt in chapter_text:
        source = build_docx([chapter_text])
    source_text = plain_text(source) if source else ""
    if excerpt not in source_text and excerpt not in chapter_text:
        return {
            "ok": False,
            "error": "文档里找不到这一条对应的原文",
            "issue_id": issue_id,
            "highlight_texts": highlight_texts_for_review(review),
        }

    new_bytes = None
    if source is not None and excerpt in plain_text(source):
        new_bytes = replace_text(source, excerpt, suggestion)
    if excerpt in chapter_text:
        _write_document_text(project, excerpt, suggestion)
    after = plain_text(new_bytes) if new_bytes is not None else collect_document_text(project)
    checked = rereview_issue_text({**target, "excerpt": excerpt, "suggestion": suggestion}, after)
    resolved = bool(checked.get("ok"))
    target["resolved"] = resolved
    target["rereview"] = checked
    if resolved:
        review[bucket_name] = [item for item in review.get(bucket_name) or [] if item.get("id") != target.get("id")]
        resolved_rows = list(review.get("resolved") or [])
        resolved_rows.append(target)
        review["resolved"] = resolved_rows
    else:
        review[bucket_name] = [
            target if item.get("id") == target.get("id") else item
            for item in review.get(bucket_name) or []
        ]
    review["status"] = "green" if not unresolved_issues(review) else review.get("status") or "red"
    checklist = dict(project.checklist_result or {})
    checklist["doc_review"] = review
    project.checklist_result = checklist
    flag_modified(project, "checklist_result")
    highlights = highlight_texts_for_review(review)
    payload = {
        "ok": resolved,
        "issue_id": target.get("id"),
        "resolved": resolved,
        "rereview": target.get("rereview"),
        "review": review,
        "highlight_texts": highlights,
        "answer": (
            f"已只修改审查问题「{excerpt}」→「{suggestion}」，并复审了这一条。"
            + ("这一条已消除。" if resolved else "复审后这一条仍在。")
        ),
    }
    if new_bytes is not None:
        payload["docx_bytes"] = new_bytes
    return payload


def wants_single_issue_fix(text: str) -> bool:
    return bool(_FIX_ISSUE_RE.search(text or ""))


def project_memory_text(db: Session | None, workspace: dict | None, context: dict | None) -> str:
    if db is None:
        return ""
    project = bound_project(db, workspace, context)
    if project is None:
        return ""
    return memo_prompt_block(project.fields)


def bound_project(db: Session, workspace: dict | None, context: dict | None) -> TenderProject | None:
    from app.services.agent_runtime import resolve_project_id

    pid = resolve_project_id(workspace, context)
    if not pid:
        return None
    return db.query(TenderProject).filter(TenderProject.id == pid).first()


def apply_project_field_patch(db: Session, project: TenderProject, patch: dict[str, Any]) -> dict[str, Any]:
    """改字段走字段定义白名单。未变化的第二步已填字段不会被重新标成待核实。"""
    from app.models import FieldDef
    from app.services.field_verify import is_verify_field, mark_fields_for_reverify

    known = {fd.key: fd for fd in db.query(FieldDef).all()}
    merged = dict(project.fields or {})
    updated: list[str] = []
    rejected: list[str] = []
    changed_verify: list[str] = []
    for key, value in (patch or {}).items():
        name = str(key)
        if name.startswith("_") or (known and name not in known and name not in merged):
            rejected.append(name)
            continue
        new_val = "" if value is None else str(value)
        old_val = "" if merged.get(name) is None else str(merged.get(name))
        if new_val == old_val:
            continue
        fd = known.get(name)
        if fd and is_verify_field(fd):
            changed_verify.append(name)
        merged[name] = new_val
        updated.append(name)
    if changed_verify:
        merged = mark_fields_for_reverify(merged, changed_verify)
    if updated:
        project.fields = merged
        flag_modified(project, "fields")
        if merged.get("project_name"):
            project.title = str(merged["project_name"])[:180]
    return {"ok": True, "updated_keys": updated, "rejected_keys": rejected, "reverified_keys": changed_verify}
