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
    ("requirement", re.compile(r"要求|评分标准|评审标准")),
    ("date", re.compile(r"日期|时间")),
    ("duration", re.compile(r"工期")),
    ("disqualification", re.compile(r"废标|否决")),
)
_DATE_FIELDS = (
    ("投标截止", re.compile(r"投标截止|递交截止|截止时间")),
    ("开标", re.compile(r"开标")),
)
_DURATION_VALUE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:个日历|日历)?\s*(个月|天|日|月|年)")


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
    open_scoring: dict[str, Any] | None = None

    def finish_scoring() -> None:
        nonlocal open_scoring
        if open_scoring and open_scoring.get("name"):
            scoring.append(open_scoring)
        open_scoring = None

    for block in blocks:
        if block.get("kind") == "table":
            finish_scoring()
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
            if kind != "scoring":
                finish_scoring()
            section = kind
            continue
        active = kind or section
        if kind and kind != "scoring":
            finish_scoring()
            section = kind
        elif kind == "scoring":
            section = "scoring"
        if active == "scoring":
            open_scoring = _take_scoring_line(text, source, scoring, open_scoring)
            continue
        finish_scoring()
        _consume_clause(
            active,
            body or text,
            source,
            scoring,
            disqualification,
            qualifications,
            dates,
        )
        if active == "duration" and not duration:
            found = _duration_in(text)
            if found:
                duration = found
                duration_source = source
    finish_scoring()
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
        name, score, requirement = _scoring_name_requirement(text)
        if name:
            scoring.append(_scoring_item(name, score, requirement, text, source, len(scoring)))
    elif kind == "disqualification":
        disqualification.append(_disqualification_item(text, source, len(disqualification)))
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
    name, score, _requirement = _scoring_name_requirement(text)
    return name, score


def _scoring_name_requirement(text: str) -> tuple[str, str, str]:
    """评分点是标题和其后的要求，不是整行关键词。"""
    raw = (text or "").strip()
    if not raw:
        return "", "", ""
    if ("。" in raw or "；" in raw) and "：" not in raw and ":" not in raw:
        return "", "", ""
    score = ""
    matched = re.search(r"(\d+\s*分)", raw)
    if matched:
        score = re.sub(r"\s+", "", matched.group(1))
        raw = f"{raw[:matched.start()]} {raw[matched.end():]}".strip()
    raw = re.sub(r"^(评分办法|评分标准|评分点|分值构成|评审因素|评分项)", "", raw)
    raw = raw.strip(" ：:，,。；; ")
    raw = re.sub(r"^[\d一二三四五六七八九十]+[、.．)\]]\s*", "", raw).strip()
    label, body = _split_label(raw)
    if label and 1 < len(label) <= 24 and not _requirement_prose(label):
        return label[:80], score, body.strip()
    if raw and len(raw) <= 24 and not _requirement_prose(raw) and "。" not in raw and "；" not in raw:
        return raw[:80], score, ""
    return "", score, ""


def _requirement_prose(text: str) -> bool:
    return bool(re.search(r"(应当|必须|须|提供|提交|建立|包含|包括|进行)", text or ""))


def _scoring_item(name: str, score: str, requirement: str, text: str, source: str, index: int) -> dict[str, Any]:
    return {
        "id": f"score:{source or index + 1}",
        "name": name[:80],
        "title": name[:80],
        "score": score,
        "requirement": (requirement or "")[:500],
        "text": ((requirement or text or name) or "")[:180],
        "source": source,
    }


def _take_scoring_line(
    text: str,
    source: str,
    scoring: list[dict[str, Any]],
    open_item: dict[str, Any] | None,
) -> dict[str, Any] | None:
    name, score, inline = _scoring_name_requirement(text)
    if name:
        if open_item and open_item.get("name"):
            scoring.append(open_item)
        return _scoring_item(name, score, inline, text, source, len(scoring))
    if open_item is not None:
        extra = text.strip()
        if extra:
            current = str(open_item.get("requirement") or "")
            open_item["requirement"] = (f"{current}\n{extra}" if current else extra)[:500]
            open_item["text"] = str(open_item["requirement"])[:180]
        return open_item
    return open_item


def _extract_constraints(text: str) -> list[dict[str, str]]:
    """抽出废标约束：禁止项看条件是否出现，强制项看条件是否缺失。"""
    found: list[dict[str, str]] = []
    for polarity, pattern in (
        ("forbid", r"(?:不得|禁止|不允许|严禁)([^，。；;、]{1,30})"),
        ("require", r"(?:必须|须具备|须|应当)([^，。；;、]{1,30})"),
    ):
        for matched in re.finditer(pattern, text or ""):
            condition = _clean_condition(matched.group(1))
            if condition and not any(item["condition"] == condition for item in found):
                found.append({"polarity": polarity, "condition": condition})
    return found


def _clean_condition(text: str) -> str:
    cleaned = (text or "").strip(" ：:，,。；;、 ")
    cleaned = re.sub(r"^(具备|提供|提交|进行|出现)", "", cleaned).strip()
    return cleaned[:40]


def _disqualification_item(text: str, source: str, index: int) -> dict[str, Any]:
    constraints = _extract_constraints(text)
    name = text[:40]
    return {
        "id": f"reject:{source or index + 1}",
        "name": name,
        "title": name,
        "constraints": constraints,
        "text": text[:180],
        "source": source,
    }


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
                requirement = _cell(row, columns.get("requirement"))
                scoring.append(_scoring_item(title, score, requirement, title, source, len(scoring)))
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
                break
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


def check_against_tender(
    draft: str,
    tender: dict[str, Any] | None,
    qualifications: list[Any] | None = None,
) -> dict[str, Any]:
    """按条款对照文稿：要求是否写到、约束是否违反、工期和日期是否同一值、资质是否在项目记录里。"""
    record = tender or {}
    if not record:
        return {"ok": False, "error": "项目未挂招标文件", "conflicts": []}
    body = draft or ""
    conflicts: list[dict[str, str]] = []
    conflicts.extend(_duration_conflicts(body, record))
    for item in _coerce_items(record.get("disqualification"), "disqualification"):
        conflicts.extend(_disqualification_conflicts(body, item))
    for item in _coerce_items(record.get("scoring_points"), "scoring"):
        conflict = _scoring_conflict(body, item)
        if conflict:
            conflicts.append(conflict)
    records = _qualification_records(qualifications if qualifications is not None else record.get("qualification_records"))
    for item in _coerce_items(record.get("qualifications"), "qualification"):
        conflict = _qualification_conflict(item, records)
        if conflict:
            conflicts.append(conflict)
    for item in _coerce_items(record.get("key_dates"), "date"):
        conflict = _date_conflict(body, item)
        if conflict:
            conflicts.append(conflict)
    return {"ok": not conflicts, "conflicts": conflicts, "error": ""}


def _duration_conflicts(body: str, record: dict[str, Any]) -> list[dict[str, str]]:
    duration_item = record.get("duration_item") if isinstance(record.get("duration_item"), dict) else {}
    expected_text = str(duration_item.get("value") or record.get("duration") or "")
    expected = _parse_duration(expected_text, labeled=False)
    actual = _parse_duration(body, labeled=True)
    if not expected or not actual:
        return []
    if expected[0] == actual[0] and expected[1] == actual[1]:
        return []
    return [{
        "kind": "duration",
        "item_id": str(duration_item.get("id") or "duration"),
        "item": "工期",
        "tender": expected[2],
        "draft": actual[2],
        "message": f"工期未通过：文稿为 {actual[2]}，招标文件为 {expected[2]}",
    }]


def _parse_duration(text: str, *, labeled: bool) -> tuple[float, str, str] | None:
    raw = text or ""
    if labeled:
        if "工期" not in raw:
            return None
        start = raw.find("工期")
        raw = raw[start:start + 24]
    matched = _DURATION_VALUE_RE.search(raw)
    if not matched:
        return None
    number = float(matched.group(1))
    unit = matched.group(2)
    if unit == "日":
        unit = "天"
    elif unit == "个月":
        unit = "月"
    shown = str(int(number)) if number == int(number) else str(number)
    return number, unit, f"{shown}{unit}"


def _disqualification_conflicts(body: str, item: dict[str, Any]) -> list[dict[str, str]]:
    name = str(item.get("name") or item.get("title") or item.get("text") or "")[:40]
    conflicts: list[dict[str, str]] = []
    for constraint in _constraints_of(item):
        condition = str(constraint.get("condition") or "")
        polarity = str(constraint.get("polarity") or "")
        if not condition:
            continue
        if polarity == "require":
            if condition in body:
                continue
            conflicts.append({
                "kind": "disqualification",
                "item_id": str(item.get("id") or ""),
                "item": name,
                "tender": condition,
                "draft": "",
                "message": f"废标项「{name}」未通过：文稿缺少「{condition}」",
            })
            continue
        if condition in body:
            conflicts.append({
                "kind": "disqualification",
                "item_id": str(item.get("id") or ""),
                "item": name,
                "tender": condition,
                "draft": condition,
                "message": f"废标项「{name}」未通过：文稿出现「{condition}」",
            })
    return conflicts


def _constraints_of(item: dict[str, Any]) -> list[dict[str, str]]:
    raw = item.get("constraints")
    if isinstance(raw, list) and raw:
        constraints = []
        for entry in raw:
            if isinstance(entry, dict) and entry.get("condition"):
                constraints.append({
                    "polarity": str(entry.get("polarity") or "forbid"),
                    "condition": str(entry.get("condition")),
                })
        if constraints:
            return constraints
    text = str(item.get("text") or item.get("title") or item.get("name") or "")
    found = _extract_constraints(text)
    if found:
        return found
    banned = re.sub(r"^(不得|禁止|不允许|严禁)", "", str(item.get("banned") or "")).strip()
    if banned:
        return [{"polarity": "forbid", "condition": banned}]
    return []


def _scoring_conflict(body: str, item: dict[str, Any]) -> dict[str, str] | None:
    name = str(item.get("name") or item.get("title") or "").strip()
    requirement = str(item.get("requirement") or "").strip()
    if not name or not requirement or name not in body:
        return None
    if _requirement_covered(body, name, requirement):
        return None
    return {
        "kind": "scoring",
        "item_id": str(item.get("id") or ""),
        "item": name,
        "tender": requirement[:180],
        "draft": name,
        "message": f"评分点「{name}」未通过：文稿重复了标题，没有覆盖要求",
    }


def _requirement_covered(body: str, name: str, requirement: str) -> bool:
    needle = re.sub(r"\s+", "", requirement or "")
    compact_name = re.sub(r"\s+", "", name or "")
    if compact_name:
        needle = needle.replace(compact_name, "")
    needle = re.sub(r"\d+分", "", needle).strip("：:，,。；;、 ")
    if len(needle) < 2:
        return True
    return needle in re.sub(r"\s+", "", body or "")


def _qualification_records(rows: Any) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for row in rows or []:
        if isinstance(row, str):
            records.append({"name": row, "keywords": ""})
            continue
        if isinstance(row, dict):
            records.append({
                "name": str(row.get("name") or row.get("title") or ""),
                "keywords": str(row.get("keywords") or ""),
            })
            continue
        records.append({
            "name": str(getattr(row, "name", "") or ""),
            "keywords": str(getattr(row, "keywords", "") or ""),
        })
    return records


def _qualification_conflict(item: dict[str, Any], records: list[dict[str, str]]) -> dict[str, str] | None:
    name = str(item.get("name") or item.get("title") or "").strip()
    if not name or _qualification_met(name, records):
        return None
    return {
        "kind": "qualification",
        "item_id": str(item.get("id") or ""),
        "item": name,
        "tender": name,
        "draft": "",
        "message": f"资质「{name}」未通过：项目资质记录里没有「{name}」",
    }


def _qualification_met(required: str, records: list[dict[str, str]]) -> bool:
    needle = re.sub(r"\s+", "", required)
    if not needle:
        return True
    for record in records:
        haystack = re.sub(r"\s+", "", f"{record.get('name') or ''}{record.get('keywords') or ''}")
        if needle in haystack:
            return True
    return False


def _date_conflict(body: str, item: dict[str, Any]) -> dict[str, str] | None:
    expected = re.sub(r"\s+", "", str(item.get("value") or ""))
    if not expected:
        return None
    label = str(item.get("label") or "关键日期")
    field = _date_field(label)
    pairs = _labeled_dates(body)
    if field == "关键日期":
        differing = [(bid_field, value) for bid_field, value in pairs if value != expected]
        if not differing:
            return None
        conflict_field, draft_value = differing[0]
    else:
        matched = [(bid_field, value) for bid_field, value in pairs if bid_field == field]
        if not matched or any(value == expected for _bid_field, value in matched):
            return None
        conflict_field = label if field in label else field
        draft_value = next(value for _bid_field, value in matched if value != expected)
    shown = conflict_field if field == "关键日期" else (label if field in label else field)
    return {
        "kind": "date",
        "item_id": str(item.get("id") or ""),
        "item": shown,
        "tender": expected,
        "draft": draft_value,
        "message": f"日期「{shown}」未通过：文稿为 {draft_value}，招标文件为 {expected}",
    }


def _date_field(label: str) -> str:
    for name, pattern in _DATE_FIELDS:
        if pattern.search(label or ""):
            return name
    return "关键日期"


def _labeled_dates(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for matched in _DATE_RE.finditer(text or ""):
        value = re.sub(r"\s+", "", matched.group(0))
        window = (text or "")[max(0, matched.start() - 16):matched.start()]
        field = "关键日期"
        for name, pattern in _DATE_FIELDS:
            if pattern.search(window):
                field = name
                break
        found.append((field, value))
    return found


def _item_label(item: Any) -> str:
    if isinstance(item, dict):
        title = str(item.get("name") or item.get("title") or item.get("label") or item.get("value") or "").strip()
        score = str(item.get("score") or "").strip()
        if title and score:
            return f"{title}（{score}）"
        return title or str(item.get("text") or "")[:40]
    return str(item)[:80]


def _coerce_items(rows: Any, kind: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in rows or []:
        if isinstance(raw, dict) and (
            raw.get("title") or raw.get("name") or raw.get("value") or raw.get("label")
            or raw.get("text") or raw.get("requirement")
        ):
            items.append(_copy_item(raw))
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


def _copy_item(raw: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, (dict, list)):
            item[str(key)] = value
        elif value is None:
            item[str(key)] = ""
        else:
            item[str(key)] = str(value)
    if item.get("name") and not item.get("title"):
        item["title"] = item["name"]
    if item.get("title") and not item.get("name"):
        item["name"] = item["title"]
    return item


def _infer_section_from_hint(text: str) -> str:
    if not text:
        return ""
    if not re.search(r"(填写|写入|撰写|补充|介绍|简介)", text):
        return ""
    if re.search(r"(公司|企业).{0,8}(介绍|简介)", text):
        return "投标人简介"
    if "技术方案" in text:
        return "技术方案"
    if "投标函" in text:
        return "投标函"
    if re.search(r"(报价|商务)", text):
        return "分项报价说明"
    return ""


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
    from app.services.document_anchor import merge_anchor_context_fields, normalize_table_location

    extra = merge_anchor_context_fields(ctx, args, nested)
    location = str(extra.get("location") or "").strip()
    if not location and block_id.startswith("tbl:"):
        location = block_id
    has_table = bool(location.startswith("tbl:")) or (
        extra.get("table_index") is not None
        and extra.get("row") is not None
        and extra.get("col") is not None
    )
    if not selected and not block_id and index is None and not path and not has_table:
        hint = str(ctx.get("instruction") or ctx.get("content") or "").strip()
        auto_title = _infer_section_from_hint(hint)
        if auto_title:
            return {
                "ok": True,
                "message": "",
                "selected_text": auto_title,
                "block_id": f"section:{auto_title}",
                "paragraph_index": None,
                "path": "",
                "auto_section": True,
            }
        return {"ok": False, "message": ANCHOR_MISSING}
    anchor = {
        "ok": True,
        "message": "",
        "selected_text": selected,
        "block_id": block_id,
        "paragraph_index": index,
        "path": path,
        "location": location,
        "table_index": extra.get("table_index"),
        "row": extra.get("row"),
        "col": extra.get("col"),
    }
    return normalize_table_location(anchor)


def anchor_can_insert(anchor: dict[str, Any]) -> bool:
    from app.services.document_anchor import anchor_can_insert_at

    return anchor_can_insert_at(anchor)


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
