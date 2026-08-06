"""条目完整性校验"""
from __future__ import annotations
from datetime import date


def _text_blob(chapters: dict, fields: dict, qualifications: list[dict], inserted_ids: list[int], template_headings: list[str] | None = None) -> str:
    chapter_text = " ".join(
        (v.get("content", "") if isinstance(v, dict) else str(v))
        for v in (chapters or {}).values()
    )
    chapter_keys = " ".join((chapters or {}).keys())
    field_text = " ".join(str(v) for v in (fields or {}).values() if v)
    field_keys = " ".join((fields or {}).keys())
    qual_text = " ".join(
        f"{q.get('name', '')} {q.get('category', '')} {q.get('keywords', '')}"
        for q in qualifications if q.get("id") in inserted_ids
    )
    headings = " ".join(template_headings or [])
    return " ".join([chapter_text, chapter_keys, field_text, field_keys, qual_text, headings])


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "") if not ch.isspace())


def _contains(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    h = _norm(haystack)
    n = _norm(needle)
    if n and n in h:
        return True
    if needle in haystack:
        return True
    # 宽松匹配：去掉常见后缀/别名
    aliases = {
        "人员配置": ["人员配置说明", "项目经理"],
        "工程概况": ["工程概况补充", "project_name"],
        "分项报价": ["分项报价说明", "bid_amount", "报价表"],
        "投标报价表": ["bid_amount", "投标总价", "报价表"],
        "投标函": ["报价函", "竞标函", "project_name", "tenderer"],
        "投标函/报价函": ["报价函", "竞标函", "投标函"],
        "工期保障措施": ["duration", "工期"],
        "法定代表人身份证明": ["法定代表人", "身份证明"],
        "授权委托书": ["授权委托"],
        "投标保证金凭证": ["投标保证金", "保证金", "谈判保证金"],
        "营业执照": ["营业执照"],
        "铁路工程专业承包资质": ["铁路", "总承包", "专业承包", "电子与智能化"],
        "近3年类似业绩": ["业绩", "合同", "中标"],
        "项目经理一级建造师证": ["建造师", "项目经理"],
        "近三年审计报告": ["审计"],
        "报价表": ["报价", "bid_amount"],
    }
    for a in aliases.get(needle, []):
        if _norm(a) in h or a in haystack:
            return True
    # 条目名截断匹配（前 6 字）
    short = n[:6]
    if len(short) >= 4 and short in h:
        return True
    return False


def run_checklist(
    checklist_items: list[dict],
    chapters: dict,
    fields: dict,
    qualifications: list[dict],
    inserted_qual_ids: list[int],
    template_headings: list[str] | None = None,
) -> dict:
    results = []
    combined = _text_blob(chapters, fields, qualifications, inserted_qual_ids, template_headings)

    inserted_blob = " ".join(
        f"{q.get('name', '')} {q.get('category', '')} {q.get('keywords', '')}"
        for q in qualifications if q.get("id") in inserted_qual_ids
    )

    for item in checklist_items:
        name = item["name"]
        section = item.get("section", "")
        required = item.get("required", "必含")
        found = _contains(combined, name)
        if not found and section == "资质":
            found = _contains(inserted_blob, name) or any(
                k in inserted_blob for k in (name[:4], "营业执照", "审计", "业绩", "体系") if k and k in name
            )

        level = "green" if found else ("yellow" if required not in ("必含", "必附") else "red")
        if not found and required == "条件必含":
            level = "yellow"
        if not found and required in ("建议", "条件必附"):
            level = "yellow"
        results.append({
            "id": item.get("id"),
            "section": section,
            "name": name,
            "required": required,
            "found": found,
            "level": level,
            "remark": item.get("remark", ""),
        })

    # 资质过期检查
    today = date.today()
    for q in qualifications:
        if q.get("id") not in inserted_qual_ids:
            continue
        if q.get("is_long_term"):
            continue
        valid_to = q.get("valid_to")
        if valid_to and valid_to < today:
            results.append({
                "id": f"qual-{q['id']}",
                "section": "资质",
                "name": f"资质已过期：{q.get('name')}",
                "required": "必含",
                "found": False,
                "level": "red",
                "remark": f"有效期至 {valid_to}",
            })
        elif valid_to:
            days = (valid_to - today).days
            if days <= 90:
                results.append({
                    "id": f"qual-warn-{q['id']}",
                    "section": "资质",
                    "name": f"资质即将到期：{q.get('name')}",
                    "required": "建议",
                    "found": True,
                    "level": "yellow",
                    "remark": f"剩余 {days} 天",
                })

    # 字段必填（兼容 bid_amount / bid_amount_upper）
    field_checks = [
        ("project_name", "项目名称", ["project_name"]),
        ("tender_no", "招标编号", ["tender_no"]),
        ("tenderer", "招标人", ["tenderer"]),
        ("bid_amount", "投标总价", ["bid_amount", "bid_amount_upper", "bid_amount_lower"]),
        ("project_manager", "项目经理", ["project_manager"]),
    ]
    for key, label, alts in field_checks:
        ok = any(bool(fields.get(k)) for k in alts)
        results.append({
            "id": f"field-{key}",
            "section": "关键字段",
            "name": label,
            "required": "必含",
            "found": ok,
            "level": "green" if ok else "red",
            "remark": "",
        })

    # 硬阻断：关键字段缺失、资质过期。条目内容缺失降为黄灯（提示补齐，不阻断导出）
    for r in results:
        rid = str(r.get("id") or "")
        hard = rid.startswith("field-") or rid.startswith("qual-")
        if r.get("level") == "red" and not hard:
            r["level"] = "yellow"
            r["remark"] = (r.get("remark") or "") + ("；" if r.get("remark") else "") + "建议补齐后复核"

    reds = sum(1 for r in results if r["level"] == "red")
    yellows = sum(1 for r in results if r["level"] == "yellow")
    status = "green" if reds == 0 and yellows == 0 else ("yellow" if reds == 0 else "red")
    return {
        "status": status,
        "summary": {"red": reds, "yellow": yellows, "green": len(results) - reds - yellows},
        "items": results,
        "can_export": reds == 0,
    }
