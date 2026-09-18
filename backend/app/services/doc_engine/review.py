"""LLM + 规则审阅：导出前质量闸门。"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services import ai, word
from app.services.doc_engine.indexer import build_document_index


async def review_document(
    docx_bytes: bytes,
    fields: dict[str, Any],
    manifest: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
    required_fields: list[str],
    db: Session | None = None,
) -> dict[str, Any]:
    """全篇审阅：残留旧值、占位符、一致性、清单块。"""
    issues: list[dict] = []
    warnings: list[dict] = []

    # 规则层
    rule_val = word.validate_export(docx_bytes, required_fields, fields)
    issues.extend(rule_val.get("issues") or [])
    warnings.extend(rule_val.get("warnings") or [])

    index = build_document_index(docx_bytes)
    full_text = index.get("full_text") or ""

    # 残留旧值检测（替换模式）
    snap_fields = (snapshot or {}).get("fields") if isinstance((snapshot or {}).get("fields"), dict) else snapshot
    if snap_fields:
        for key, entry in snap_fields.items():
            if not isinstance(entry, dict):
                continue
            old_val = str(entry.get("value") or "").strip()
            new_val = str(fields.get(key) or "").strip()
            if not old_val or not new_val or old_val == new_val:
                continue
            if len(old_val) >= 4 and old_val in full_text:
                issues.append({
                    "level": "red",
                    "code": "stale_value",
                    "message": f"文档中仍残留旧「{key}」内容：{old_val[:40]}…",
                    "field": key,
                })

    # Manifest 必填块
    if manifest:
        for block in manifest.get("blocks") or []:
            if not block.get("required"):
                continue
            btype = block.get("type")
            if btype == "field_slot":
                key = block.get("bind") or ""
                if key and not fields.get(key):
                    issues.append({
                        "level": "red",
                        "code": "missing_field",
                        "message": f"必填字段未填写：{key}",
                        "field": key,
                    })
            elif btype == "ai_section":
                title = block.get("title") or ""
                marker = f"【AI_GENERATED:{title}】"
                if marker in full_text:
                    warnings.append({
                        "level": "yellow",
                        "code": "ai_not_generated",
                        "message": f"AI 章节未生成：{title}",
                    })
            elif btype == "table_slot":
                bind = block.get("bind") or ""
                cols = block.get("columns") or []
                raw = fields.get(bind)
                if bind and not raw:
                    warnings.append({
                        "level": "yellow",
                        "code": "table_empty",
                        "message": f"表格槽未填写数据：{bind}",
                        "field": bind,
                    })
                elif cols and isinstance(raw, list) and raw:
                    for i, row in enumerate(raw):
                        if not isinstance(row, dict):
                            continue
                        missing = [c for c in cols if not str(row.get(c) or "").strip()]
                        if missing:
                            warnings.append({
                                "level": "yellow",
                                "code": "table_row_incomplete",
                                "message": f"表格 {bind} 第{i + 1} 行缺少：{', '.join(missing)}",
                            })
                            break

    # LLM 审阅层（有 key 时）
    llm_findings = await _llm_review(full_text, fields, snapshot, db=db)
    for f in llm_findings:
        level = f.get("level") or "yellow"
        item = {
            "level": level,
            "code": f.get("code") or "llm_review",
            "message": f.get("message") or "",
        }
        if level == "red":
            issues.append(item)
        else:
            warnings.append(item)

    status = "green"
    if issues:
        status = "red"
    elif warnings:
        status = "yellow"

    can_export = len([i for i in issues if i.get("level") == "red"]) == 0

    return {
        "status": status,
        "can_export": can_export,
        "issues": issues,
        "warnings": warnings,
        "engine": "doc_engine_v2",
    }


async def _llm_review(
    document_text: str,
    fields: dict[str, Any],
    snapshot: dict | None,
    db: Session | None = None,
) -> list[dict]:
    if not document_text.strip():
        return []
    old_values = {}
    snap_fields = (snapshot or {}).get("fields") if isinstance((snapshot or {}).get("fields"), dict) else snapshot
    if snap_fields:
        for k, v in snap_fields.items():
            if isinstance(v, dict):
                old_values[k] = v.get("value")
            else:
                old_values[k] = v

    prompt = (
        "你是标书质量审阅专家。检查文档是否存在：\n"
        "1. 旧项目信息残留（与 new_fields 不一致的 old_values 仍出现）\n"
        "2. 金额大小写矛盾\n"
        "3. 关键字段缺失或明显错误\n\n"
        f"new_fields: {json.dumps(fields, ensure_ascii=False)[:3000]}\n"
        f"old_values: {json.dumps(old_values, ensure_ascii=False)[:1500]}\n"
        f"document_excerpt:\n{document_text[:12000]}\n\n"
        "返回 JSON 数组，每项含 level(red|yellow), code, message。最多 10 项。只返回 JSON。"
    )
    raw = await ai.chat_completion([
        {"role": "system", "content": "你是标书审阅助手，只输出 JSON 数组。"},
        {"role": "user", "content": prompt},
    ], db=db)
    if not raw:
        return []
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []
