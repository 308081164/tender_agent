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


_SECTION_RULES = (
    ("scoring", re.compile(r"评分办法|评分标准|评分点|分值构成|评审因素|评分项")),
    ("disqualification", re.compile(r"废标|否决投标|无效投标|按废标")),
    ("qualification", re.compile(r"资质要求|投标人资格|资格条件|资质条件")),
    ("duration", re.compile(r"工期")),
    ("date", re.compile(r"投标截止|开标时间|关键日期|时间安排|递交截止|截止时间")),
)
_TABLE_COLUMNS = (
    ("title", re.compile(r"评分项|评审因素|评审项|评分内容|评审内容")),
    ("score", re.compile(r"分值|得分|分数")),
    ("qualification", re.compile(r"资质|证书")),
    ("date", re.compile(r"日期|时间")),
    ("duration", re.compile(r"工期")),
    ("disqualification", re.compile(r"废标|否决")),
)


def tender_has_items(parsed: dict[str, Any] | None) -> bool:
    data = parsed or {}
    return bool(
        data.get("duration")
        or data.get("scoring_points")
        or data.get("disqualification")
        or data.get("qualifications")
        or data.get("key_dates")
    )


def parse_tender_text(text: str) -> dict[str, Any]:
    """把已经抽出的 PDF/纯文本收成条款结构。不把 PDF 字节当 UTF-8。"""
    return _structure_from_blocks(_blocks_from_plain(text), excerpt=(text or "").strip()[:4000])


def parse_tender_docx(data: bytes) -> dict[str, Any]:
    """从 docx 的段落和表格单元格建评分点、废标项、工期、资质、日期。"""
    from app.services.docx_ooxml import document_blocks, document_text

    blocks = document_blocks(data)
    return _structure_from_blocks(blocks, excerpt=document_text(data)[:4000])


def _blocks_from_plain(text: str) -> list[dict[str, Any]]:
    """PDF 文本里连续的表格行收成表，其余按段。"""
    lines = (text or "").splitlines()
    blocks: list[dict[str, Any]] = []
    paragraph_index = 0
    table_index = 0
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if _plain_table_row(line) and index + 1 < len(lines) and _plain_table_row(lines[index + 1].strip()):
            rows: list[list[str]] = []
            while index < len(lines) and _plain_table_row(lines[index].strip()):
                rows.append(_split_plain_row(lines[index].strip()))
                index += 1
            blocks.append({
                "kind": "table",
                "index": table_index,
                "rows": rows,
                "source": f"table:{table_index}",
            })
            table_index += 1
            continue
        blocks.append({
            "kind": "paragraph",
            "index": paragraph_index,
            "text": line,
            "source": f"paragraph:{paragraph_index}",
        })
        paragraph_index += 1
        index += 1
    return blocks


def _plain_table_row(line: str) -> bool:
    if not line:
        return False
    if "|" in line or "\t" in line:
        return True
    return len(re.split(r"\s{2,}", line)) >= 2


def _split_plain_row(line: str) -> list[str]:
    if "|" in line:
        return [cell.strip() for cell in line.strip("|").split("|")]
    if "\t" in line:
        return [cell.strip() for cell in line.split("\t")]
    return [cell.strip() for cell in re.split(r"\s{2,}", line)]


def _structure_from_blocks(blocks: list[dict[str, Any]], *, excerpt: str) -> dict[str, Any]:
    scoring: list[dict[str, str]] = []
    disqualification: list[dict[str, str]] = []
    qualifications: list[dict[str, str]] = []
    dates: list[dict[str, str]] = []
    duration = ""
    duration_source = ""
    section = ""
    for block in blocks:
        if block.get("kind") == "table":
            _consume_tender_table(
                block,
                section,
                scoring,
                disqualification,
                qualifications,
                dates,
            )
            found, source = _duration_from_table(block, section)
            if found and not duration:
                duration = found
                duration_source = source
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        source = str(block.get("source") or "")
        kind, body = _classify_clause(text)
        if _is_section_heading(text, kind):
            section = kind
            continue
        if kind:
            section = kind
        _consume_clause(
            kind or section,
            body or text,
            source,
            scoring,
            disqualification,
            qualifications,
            dates,
        )
        if (kind or section) == "duration" and not duration:
            found = _duration_in(text)
            if found:
                duration = found
                duration_source = source
    return {
        "scoring_points": scoring[:30],
        "disqualification": disqualification[:30],
        "duration": duration,
        "duration_item": (
            {"id": "duration", "title": "工期", "value": duration, "source": duration_source}
            if duration else {}
        ),
        "qualifications": qualifications[:30],
        "key_dates": dates[:20],
        "excerpt": excerpt,
    }


def _classify_clause(text: str) -> tuple[str, str]:
    label, body = _split_label(text)
    probe = label if label and len(label) <= 24 else text
    for kind, pattern in _SECTION_RULES:
        if pattern.search(probe):
            return kind, body or text
    return "", text


def _split_label(text: str) -> tuple[str, str]:
    for sep in ("：", ":"):
        if sep in text:
            label, body = text.split(sep, 1)
            return label.strip(), body.strip()
    return "", text.strip()


def _is_section_heading(text: str, kind: str) -> bool:
    if not kind or len(text) > 24:
        return False
    if any(mark in text for mark in ("：", ":", "，", "。", "不得")):
        return False
    if _DURATION_RE.search(text) or _DATE_RE.search(text) or re.search(r"\d+\s*分", text):
        return False
    return True


def _consume_clause(
    kind: str,
    text: str,
    source: str,
    scoring: list[dict[str, str]],
    disqualification: list[dict[str, str]],
    qualifications: list[dict[str, str]],
    dates: list[dict[str, str]],
) -> None:
    text = (text or "").strip()
    if not text or not kind:
        return
    if kind == "scoring":
        title, score = _scoring_fields(text)
        if title:
            scoring.append({
                "id": f"score:{source or len(scoring) + 1}",
                "title": title[:80],
                "score": score,
                "text": text[:180],
                "source": source,
            })
    elif kind == "disqualification":
        banned = ""
        matched = re.search(r"不得([^，。；]{2,24})", text)
        if matched:
            banned = matched.group(1)
        disqualification.append({
            "id": f"reject:{source or len(disqualification) + 1}",
            "title": banned or text[:40],
            "banned": banned,
            "text": text[:180],
            "source": source,
        })
    elif kind == "qualification":
        title = re.sub(r"^(资质要求|投标人须具备|须具备|资质)", "", text).strip(" ：:，,")
        if title:
            qualifications.append({
                "id": f"qual:{source or len(qualifications) + 1}",
                "title": title[:80],
                "text": text[:180],
                "source": source,
            })
    elif kind == "date":
        label, _body = _split_label(text)
        if not label:
            label = _DATE_RE.sub("", text).strip(" ：:，,。；; ") or "关键日期"
        for raw in _DATE_RE.findall(text):
            value = re.sub(r"\s+", "", raw)
            dates.append({
                "id": f"date:{source or len(dates) + 1}:{value}",
                "label": (label or "关键日期")[:40],
                "value": value,
                "text": text[:180],
                "source": source,
            })


def _scoring_fields(text: str) -> tuple[str, str]:
    score = ""
    matched = re.search(r"(\d+\s*分)", text or "")
    if matched:
        score = re.sub(r"\s+", "", matched.group(1))
        title = (text or "")[:matched.start()]
    else:
        title = text or ""
    title = re.sub(r"^(评分办法|评分标准|评分点|分值构成|评审因素)", "", title)
    title = title.strip(" ：:，,。；; ")
    return title[:80], score


def _consume_tender_table(
    block: dict[str, Any],
    section: str,
    scoring: list[dict[str, str]],
    disqualification: list[dict[str, str]],
    qualifications: list[dict[str, str]],
    dates: list[dict[str, str]],
) -> None:
    rows = [list(row) for row in (block.get("rows") or []) if any(str(cell).strip() for cell in row)]
    if not rows:
        return
    columns = _table_columns(rows[0])
    data_rows = rows[1:] if columns else rows
    source_base = str(block.get("source") or "table")
    if not columns:
        for offset, row in enumerate(rows):
            for cell_index, cell in enumerate(row):
                text = str(cell).strip()
                if not text:
                    continue
                kind, body = _classify_clause(text)
                source = f"{source_base}:r{offset}:c{cell_index}"
                _consume_clause(
                    kind or section, body or text, source,
                    scoring, disqualification, qualifications, dates,
                )
        return
    for offset, row in enumerate(data_rows):
        source = f"{source_base}:r{offset + 1}"
        if "title" in columns or "score" in columns:
            title = _cell(row, columns.get("title"))
            score = re.sub(r"\s+", "", _cell(row, columns.get("score")))
            if not title and score:
                title, parsed_score = _scoring_fields(" ".join(row))
                score = score or parsed_score
            if title:
                scoring.append({
                    "id": f"score:{source}",
                    "title": title[:80],
                    "score": score,
                    "text": title[:180],
                    "source": source,
                })
        if "qualification" in columns:
            title = _cell(row, columns["qualification"])
            if title:
                qualifications.append({
                    "id": f"qual:{source}",
                    "title": title[:80],
                    "text": title[:180],
                    "source": source,
                })
        if "disqualification" in columns:
            text = _cell(row, columns["disqualification"])
            if text:
                _consume_clause("disqualification", text, source, scoring, disqualification, qualifications, dates)
        if "date" in columns:
            text = _cell(row, columns["date"])
            label = _cell(row, columns.get("title")) or "关键日期"
            if text:
                _consume_clause("date", f"{label}：{text}", source, scoring, disqualification, qualifications, dates)


def _table_columns(header: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, cell in enumerate(header):
        for name, pattern in _TABLE_COLUMNS:
            if name not in found and pattern.search(str(cell)):
                found[name] = index
    return found


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def _duration_from_table(block: dict[str, Any], section: str) -> tuple[str, str]:
    rows = block.get("rows") or []
    if not rows:
        return "", ""
    columns = _table_columns(rows[0])
    source_base = str(block.get("source") or "table")
    if "duration" in columns:
        for offset, row in enumerate(rows[1:] or rows[:1]):
            found = _duration_in(_cell(row, columns["duration"]))
            if found:
                return found, f"{source_base}:r{offset + 1}"
    if section == "duration":
        for offset, row in enumerate(rows):
            found = _duration_in(" ".join(str(cell) for cell in row))
            if found:
                return found, f"{source_base}:r{offset}"
    for offset, row in enumerate(rows):
        for cell_index, cell in enumerate(row):
            found = _duration_in(str(cell))
            if found:
                return found, f"{source_base}:r{offset}:c{cell_index}"
    return "", ""


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
            parts.append(f"- {label}：" + "；".join(_item_label(x) for x in rows[:6]))
    return "\n".join(parts)


def _duration_in(text: str) -> str:
    if "工期" not in (text or ""):
        return ""
    found = _DURATION_RE.search(text or "")
    if not found:
        return ""
    return re.sub(r"\s+", "", found.group(1))


def check_against_tender(draft: str, tender: dict[str, Any] | None) -> dict[str, Any]:
    """把结构化条款逐条对照文稿，并写明是哪一条没通过。"""
    record = tender or {}
    if not record:
        return {"ok": False, "error": "项目未挂招标文件", "conflicts": []}
    body = draft or ""
    conflicts: list[dict[str, str]] = []
    duration_item = record.get("duration_item") if isinstance(record.get("duration_item"), dict) else {}
    expected = re.sub(r"\s+", "", str(duration_item.get("value") or record.get("duration") or ""))
    actual = _duration_in(body)
    if expected and actual and expected != actual:
        conflicts.append({
            "kind": "duration",
            "item_id": str(duration_item.get("id") or "duration"),
            "item": "工期",
            "tender": expected,
            "draft": actual,
            "message": f"工期未通过：文稿为 {actual}，招标文件为 {expected}",
        })
    for item in _coerce_items(record.get("disqualification"), "disqualification"):
        banned = str(item.get("banned") or "")
        if not banned:
            matched = re.search(r"不得([^，。；]{2,24})", str(item.get("text") or item.get("title") or ""))
            banned = matched.group(1) if matched else ""
        if banned and banned in body:
            name = _item_label(item)
            conflicts.append({
                "kind": "disqualification",
                "item_id": str(item.get("id") or ""),
                "item": name,
                "tender": str(item.get("text") or name)[:180],
                "draft": banned,
                "message": f"废标项「{name}」未通过：文稿出现「{banned}」",
            })
    for item in _coerce_items(record.get("scoring_points"), "scoring"):
        title = str(item.get("title") or "").strip()
        if title and title not in body:
            conflicts.append({
                "kind": "scoring",
                "item_id": str(item.get("id") or ""),
                "item": title,
                "tender": str(item.get("text") or title)[:180],
                "draft": "",
                "message": f"评分点「{title}」未写入文稿",
            })
    for item in _coerce_items(record.get("qualifications"), "qualification"):
        title = str(item.get("title") or "").strip()
        if title and title not in body:
            conflicts.append({
                "kind": "qualification",
                "item_id": str(item.get("id") or ""),
                "item": title,
                "tender": str(item.get("text") or title)[:180],
                "draft": "",
                "message": f"资质「{title}」未写入文稿",
            })
    draft_dates = [re.sub(r"\s+", "", item) for item in _DATE_RE.findall(body)]
    for item in _coerce_items(record.get("key_dates"), "date"):
        expected_date = re.sub(r"\s+", "", str(item.get("value") or ""))
        label = str(item.get("label") or "关键日期")
        if not expected_date or expected_date in body:
            continue
        if not re.search(r"截止|开标|日期|时间", body) and label not in body:
            continue
        other = next((found for found in draft_dates if found != expected_date), "")
        if not other and not draft_dates:
            continue
        conflicts.append({
            "kind": "date",
            "item_id": str(item.get("id") or ""),
            "item": label,
            "tender": expected_date,
            "draft": other or (draft_dates[0] if draft_dates else ""),
            "message": f"日期「{label}」未通过：文稿为 {other or '另一日期'}，招标文件为 {expected_date}",
        })
    return {"ok": not conflicts, "conflicts": conflicts, "error": ""}


def _item_label(item: Any) -> str:
    if isinstance(item, dict):
        title = str(item.get("title") or item.get("label") or item.get("value") or "").strip()
        score = str(item.get("score") or "").strip()
        if title and score:
            return f"{title}（{score}）"
        return title or str(item.get("text") or "")[:40]
    return str(item)[:80]


def _coerce_items(rows: Any, kind: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw in rows or []:
        if isinstance(raw, dict) and (raw.get("title") or raw.get("value") or raw.get("label") or raw.get("text")):
            items.append({str(key): str(value or "") for key, value in raw.items()})
            continue
        text = str(raw or "").strip()
        if not text:
            continue
        parsed = _structure_from_blocks(
            [{"kind": "paragraph", "index": 0, "text": text, "source": "stored"}],
            excerpt=text,
        )
        bucket = {
            "scoring": "scoring_points",
            "disqualification": "disqualification",
            "qualification": "qualifications",
            "date": "key_dates",
        }[kind]
        found = parsed.get(bucket) or []
        if found:
            items.extend(found)
        elif kind == "date" and _DATE_RE.search(text):
            value = re.sub(r"\s+", "", _DATE_RE.search(text).group(0))
            items.append({"id": f"date:stored:{value}", "label": "关键日期", "value": value, "text": text, "source": "stored"})
    return items


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


_FIELD_LOCATIONS = {
    "duration": "工期",
    "project_name": "项目名称",
    "tender_no": "招标编号",
    "tenderer": "招标人",
    "project_manager": "项目经理",
}


def open_bound_docx(db: Session | None, project: TenderProject | None, session=None) -> bytes | None:
    """工作台正在看的 docx：会话草稿优先，其次项目草稿键。"""
    keys: list[str] = []
    if session is not None:
        ws = getattr(session, "workspace", None) or {}
        keys.extend([str(ws.get("draft_object_key") or ""), str(ws.get("template_object_key") or "")])
    elif db is not None and project is not None:
        from app.services.project_sessions import find_bound_session

        bound = find_bound_session(db, project.id)
        if bound is not None:
            ws = bound.workspace or {}
            keys.extend([str(ws.get("draft_object_key") or ""), str(ws.get("template_object_key") or "")])
    if project is not None:
        keys.append(str((project.fields or {}).get("_draft_object_key") or ""))
    from app.services import storage

    for key in keys:
        if not key:
            continue
        try:
            data = storage.download_bytes(key)
        except Exception:
            continue
        if data:
            return data
    return None


def derive_excerpt_from_document(issue: dict[str, Any], docx_bytes: bytes | None, chapter_text: str) -> str:
    """审查项没有原文时，从打开的文档位置推出要替换的片段。"""
    quoted = _quoted_excerpt(str(issue.get("message") or ""))
    if quoted:
        return quoted
    from app.services.docx_ooxml import paragraphs as docx_paragraphs

    nodes: list[str] = []
    if docx_bytes:
        try:
            nodes = [line.strip() for line in docx_paragraphs(docx_bytes)]
        except Exception:
            nodes = []
    if not nodes and chapter_text:
        nodes = [line.strip() for line in chapter_text.splitlines() if line.strip()]
    suggestion = str(issue.get("suggestion") or "").strip()
    index = _optional_index(issue.get("paragraph_index"))
    block_id = str(issue.get("block_id") or "")
    if index is None and block_id:
        matched = re.search(r"(?:^|:)(\d+)$", block_id)
        if matched and (block_id.startswith("p:") or block_id.startswith("section:") or block_id.startswith("block:")):
            index = int(matched.group(1))
    if index is not None and 0 <= index < len(nodes):
        located = _replacement_token(nodes[index], suggestion, str(issue.get("field") or ""))
        if located:
            return located
    label = _FIELD_LOCATIONS.get(str(issue.get("field") or ""), "")
    for line in nodes:
        if label and label not in line:
            continue
        located = _replacement_token(line, suggestion, str(issue.get("field") or ""))
        if located:
            return located
    return ""


def _replacement_token(paragraph: str, suggestion: str, field: str) -> str:
    text = (paragraph or "").strip()
    if not text or text == suggestion:
        return ""
    if field == "duration" or _DURATION_RE.fullmatch(suggestion or ""):
        found = _DURATION_RE.search(text)
        if found:
            token = re.sub(r"\s+", "", found.group(1))
            if token and token != suggestion:
                return token
    for raw in _DATE_RE.findall(text):
        token = re.sub(r"\s+", "", raw)
        if token and token != suggestion:
            return token
    if suggestion and suggestion not in text and len(text) <= 80:
        return text
    return ""


def _issue_still_reported(issue: dict[str, Any], review: dict[str, Any]) -> bool:
    code = str(issue.get("code") or "")
    field = str(issue.get("field") or "")
    excerpt = str(issue.get("excerpt") or "").strip()
    for _bucket, item in iter_review_issues(review):
        if code and item.get("code") == code and (not field or str(item.get("field") or "") == field):
            return True
        if excerpt and excerpt == str(item.get("excerpt") or "").strip():
            return True
    return False


async def rereview_issue_on_document(
    project: TenderProject,
    issue: dict[str, Any],
    docx_bytes: bytes,
    db: Session | None = None,
) -> dict[str, Any]:
    """用导出同一套 review_document 复审这一条，不看摘录是否还在字符串里。"""
    from app.services.doc_engine.engine import review_project_document

    fields = dict(project.fields or {})
    field = str(issue.get("field") or "")
    suggestion = str(issue.get("suggestion") or "").strip()
    excerpt = str(issue.get("excerpt") or "").strip()
    if field and suggestion:
        fields[field] = suggestion
    snapshot = None
    if field and excerpt:
        snapshot = {"fields": {field: {"value": excerpt}}}
    placeholders = None
    if db is not None and getattr(project, "template_id", None):
        from app.models import Template

        template = db.query(Template).filter(Template.id == project.template_id).first()
        if template is not None:
            placeholders = template.placeholders
            if snapshot is None and isinstance(getattr(template, "source_snapshot", None), dict):
                snapshot = template.source_snapshot
    fresh = await review_project_document(
        docx_bytes, placeholders, fields, snapshot, [], db=db,
    )
    still = _issue_still_reported(issue, fresh)
    return {
        "issue_id": issue.get("id"),
        "ok": not still,
        "checked_on": "review_document",
        "still_reported": still,
    }


async def fix_review_issue(
    project: TenderProject,
    issue_id: str,
    docx_bytes: bytes | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """只改指定审查问题，写入打开的 docx，再用 review_document 复审这一条。"""
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
    from app.services.docx_ooxml import build_docx, paragraphs as docx_paragraphs, plain_text, replace_text

    chapter_text = collect_document_text(project)
    source = docx_bytes
    if not excerpt:
        excerpt = derive_excerpt_from_document(target, source, chapter_text)
        if excerpt:
            target["excerpt"] = excerpt
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
    checked_bytes = new_bytes if new_bytes is not None else source
    if checked_bytes is None:
        checked_bytes = build_docx(docx_paragraphs(source) if source else [collect_document_text(project)])
    checked = await rereview_issue_on_document(
        project,
        {**target, "excerpt": excerpt, "suggestion": suggestion},
        checked_bytes,
        db,
    )
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
