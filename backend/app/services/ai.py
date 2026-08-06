"""AI 服务：支持 DeepSeek / 通义千问，无 Key 时使用本地模板生成"""
from __future__ import annotations
import httpx
from sqlalchemy.orm import Session

from app.services import settings_svc

CHAPTER_TEMPLATES = {
    "施工组织设计": (
        "针对「{project_name}」项目，我方拟采用分段流水施工组织方式。"
        "关键控制节点包括路基填筑、桥梁架设、轨道铺设及联调联试。"
        "工期安排为{duration}，项目经理为{project_manager}。"
        "施工期间严格执行铁路工程相关技术规范，配备专职安全员和质量员，实行日报周报制度，"
        "确保安全、质量、进度全面受控。"
    ),
    "人员配置说明": (
        "本项目拟配备项目经理{project_manager}（一级建造师·铁路工程），"
        "技术负责人具备高级工程师职称，安全负责人持安全员B证。"
        "关键岗位人员均持证上岗，满足「{project_name}」招标文件人员资格要求。"
    ),
    "质量与安全保证措施": (
        "建立三级质量检查体系，关键工序实行旁站与专检相结合；"
        "严格执行《铁路工程施工安全技术规程》，落实班前交底与隐患排查。"
        "针对「{project_name}」工程特点，制定专项安全技术方案，确保施工全过程可控。"
    ),
    "工期保障措施": (
        "我方承诺「{project_name}」工期为{duration}，将编制详细进度计划，"
        "设置里程碑节点考核，配置充足劳动力与机械设备，雨季与交叉施工提前预案，"
        "确保按期完工并预留合理赶工余地。"
    ),
    "分项报价说明": (
        "本项目投标总价为{bid_amount}，报价已综合考虑人工、材料、机械、管理费及合理利润，"
        "符合「{project_name}」招标文件计价要求，分项明细可按招标清单进一步细化。"
    ),
    "工程概况补充": (
        "「{project_name}」由{tenderer}组织招标，招标编号{tender_no}。"
        "投标人{bidder}具备相应资质与类似业绩，承诺按约定工期{duration}完成建设任务。"
    ),
}


async def chat_completion(
    messages: list[dict],
    provider: str | None = None,
    db: Session | None = None,
) -> str:
    """调用外部 LLM；失败或无 Key 时返回空字符串，由上层走模板兜底。"""
    cfg = settings_svc.resolve_ai_config(db)
    use_provider = provider or cfg.get("preferred_provider") or "auto"

    order = []
    if use_provider == "deepseek":
        order = ["deepseek"]
    elif use_provider == "qwen":
        order = ["qwen"]
    else:
        order = ["deepseek", "qwen"]

    for name in order:
        if name == "deepseek" and cfg.get("deepseek_api_key"):
            try:
                return await _openai_compat(
                    cfg["deepseek_base_url"],
                    cfg["deepseek_api_key"],
                    cfg.get("deepseek_model") or "deepseek-chat",
                    messages,
                )
            except Exception:
                if use_provider == "deepseek":
                    return ""
                continue
        if name == "qwen" and cfg.get("qwen_api_key"):
            try:
                return await _openai_compat(
                    cfg["qwen_base_url"],
                    cfg["qwen_api_key"],
                    cfg.get("qwen_model") or "qwen-plus",
                    messages,
                )
            except Exception:
                if use_provider == "qwen":
                    return ""
                continue
    return ""


async def _openai_compat(base_url: str, api_key: str, model: str, messages: list[dict]) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": 0.4}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def local_chapter_text(chapter_key: str, fields: dict) -> str:
    tpl = CHAPTER_TEMPLATES.get(chapter_key)
    if not tpl:
        return (
            f"关于「{fields.get('project_name', '本项目')}」的{chapter_key}内容："
            f"投标人{fields.get('bidder', '')}将严格按照招标文件及行业规范组织实施，"
            f"确保工期{fields.get('duration', '')}、质量与安全目标全面达成。"
        )
    safe = {k: fields.get(k, "") or "" for k in (
        "project_name", "tender_no", "tenderer", "bidder",
        "bid_amount", "duration", "project_manager", "warranty_period",
    )}
    try:
        return tpl.format(**safe)
    except Exception:
        return tpl


async def generate_chapter(
    chapter_key: str,
    fields: dict,
    db: Session | None = None,
    company_context: str = "",
) -> dict:
    style = (
        "正式严谨，符合铁路/轨道交通行业规范；禁止口语化；"
        "数字、日期、金额须前后一致；全面响应招标要求。"
    )
    ctx = (company_context or "")[:2500]
    prompt = (
        f"你是铁路行业标书撰写助手。请为章节「{chapter_key}」撰写正式、严谨的中文段落，"
        f"约200-400字。\n文风要求：{style}\n企业背景：{ctx}\n项目信息：{fields}。"
        f"不要使用口语，不要编造无法核实的资质编号。"
    )
    ai_text = await chat_completion([
        {"role": "system", "content": "你是专业的铁路工程标书撰写助手。"},
        {"role": "user", "content": prompt},
    ], db=db)
    text = ai_text.strip() if ai_text else local_chapter_text(chapter_key, fields)
    return {
        "chapter": chapter_key,
        "content": text,
        "source": "ai" if ai_text else "template",
        "highlight_fields": [k for k, v in fields.items() if v and k in text],
    }


async def answer_faq(
    question: str,
    faq_items: list[dict],
    db: Session | None = None,
    history: list[dict] | None = None,
) -> dict:
    q = question.strip()
    best = None
    best_score = 0.0
    for item in faq_items:
        q_chars = set(q)
        i_chars = set(item["question"])
        score = len(q_chars & i_chars) / max(len(q_chars), 1)
        if any(w in item["question"] for w in q if len(w) > 1):
            score += 0.2
        for word in ["资质", "业绩", "项目经理", "建造师", "审计", "行贿", "安全", "地铁", "铁路"]:
            if word in q and word in (item["question"] + item["answer"] + item.get("category", "")):
                score += 0.3
        if score > best_score:
            best_score = score
            best = item

    # 多轮上下文：取最近若干条
    hist = []
    for m in (history or [])[-8:]:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            hist.append({"role": role, "content": content})

    if best and best_score > 0.15:
        answer = best["answer"]
        source = best.get("source", "")
        messages = [
            {"role": "system", "content": "你是企业资质与投标问答助手。基于标准答案简要回答，不要改变事实。"},
            *hist,
            {"role": "user", "content": f"问题：{q}\n标准答案：{answer}"},
        ]
        polished = await chat_completion(messages, db=db)
        if polished:
            answer = polished.strip()
        return {"answer": answer, "source": source, "matched_question": best["question"], "mode": "kb"}

    messages = [
        {"role": "system", "content": "你是企业问答助手。若无法从企业资料确认，请明确说明需人工核实。"},
        *hist,
        {"role": "user", "content": q},
    ]
    fallback = await chat_completion(messages, db=db)
    if fallback:
        return {"answer": fallback.strip(), "source": "", "matched_question": "", "mode": "ai"}
    return {
        "answer": "暂未在企业资质库中匹配到明确答案，建议人工核查相关招标条款与资质材料。",
        "source": "",
        "matched_question": "",
        "mode": "fallback",
    }


async def test_provider(provider: str, db: Session | None = None) -> dict:
    """连通性测试"""
    cfg = settings_svc.resolve_ai_config(db)
    if provider == "deepseek":
        if not cfg.get("deepseek_api_key"):
            return {"ok": False, "message": "未配置 DeepSeek API Key"}
        try:
            text = await _openai_compat(
                cfg["deepseek_base_url"],
                cfg["deepseek_api_key"],
                cfg.get("deepseek_model") or "deepseek-chat",
                [{"role": "user", "content": "请只回复：ok"}],
            )
            return {"ok": True, "message": "DeepSeek 连接成功", "sample": (text or "")[:80]}
        except Exception as e:
            return {"ok": False, "message": f"DeepSeek 连接失败：{e}"}
    if provider == "qwen":
        if not cfg.get("qwen_api_key"):
            return {"ok": False, "message": "未配置通义千问 API Key"}
        try:
            text = await _openai_compat(
                cfg["qwen_base_url"],
                cfg["qwen_api_key"],
                cfg.get("qwen_model") or "qwen-plus",
                [{"role": "user", "content": "请只回复：ok"}],
            )
            return {"ok": True, "message": "通义千问连接成功", "sample": (text or "")[:80]}
        except Exception as e:
            return {"ok": False, "message": f"通义千问连接失败：{e}"}
    return {"ok": False, "message": "未知供应商"}
