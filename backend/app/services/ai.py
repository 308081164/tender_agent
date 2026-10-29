"""AI 服务：支持 DeepSeek / 通义千问 / Kimi（月之暗面），无 Key 时使用本地模板生成"""
from __future__ import annotations
import json
from collections.abc import AsyncIterator

import httpx
from sqlalchemy.orm import Session

from app.services import settings_svc

TEXT_TASK_KINDS = frozenset({"text", "text_batch", "chat"})
MULTIMODAL_TASK_KINDS = frozenset({"multimodal", "vision", "qual_folder_classify", "qual_folder"})
SETTINGS_PATH = "/settings"


class MultimodalRequiredError(Exception):
    """未配置千问 VL / Kimi K3 时阻止多模态任务。"""

    def user_message(self) -> str:
        return settings_svc.multimodal_warning_message()

    def actions(self) -> list[dict]:
        return [
            {"type": "link", "label": "打开系统设置", "url": SETTINGS_PATH, "primary": True},
        ]

    def payload(self) -> dict:
        return settings_svc.multimodal_gate_payload()


def is_multimodal_ready(db: Session | None = None) -> bool:
    return settings_svc.multimodal_ready(settings_svc.resolve_ai_config(db))


def require_multimodal(db: Session | None = None) -> None:
    if not is_multimodal_ready(db):
        raise MultimodalRequiredError()


def pick_model(task_kind: str, cfg: dict) -> list[str]:
    """返回 provider 尝试顺序（内部 slug）。"""
    kind = (task_kind or "text").strip().lower()
    if kind in MULTIMODAL_TASK_KINDS:
        order: list[str] = []
        if settings_svc.deepseek_multimodal_ready(cfg):
            order.append("deepseek")
        if settings_svc.qwen_vl_ready(cfg):
            order.append("qwen_vl")
        if settings_svc.kimi_k3_ready(cfg):
            order.append("kimi_k3")
        return order
    if kind in TEXT_TASK_KINDS:
        order = []
        if cfg.get("deepseek_api_key"):
            order.append("deepseek")
        if cfg.get("qwen_api_key"):
            order.append("qwen")
        if cfg.get("kimi_api_key"):
            order.append("kimi")
        pref = (cfg.get("preferred_provider") or "auto").strip()
        if pref == "deepseek" and "deepseek" in order:
            return ["deepseek"]
        if pref == "qwen" and "qwen" in order:
            return ["qwen"]
        if pref == "kimi" and "kimi" in order:
            return ["kimi"]
        return order
    return pick_model("text", cfg)


def _provider_call(slug: str, cfg: dict, *, vision: bool = False) -> tuple[str, str, str] | None:
    """base_url, api_key, model"""
    if slug == "deepseek" and cfg.get("deepseek_api_key"):
        return (
            cfg["deepseek_base_url"],
            cfg["deepseek_api_key"],
            cfg.get("deepseek_model") or settings_svc.DEEPSEEK_DEFAULT_MODEL,
        )
    if slug == "qwen" and cfg.get("qwen_api_key"):
        return (
            cfg["qwen_base_url"],
            cfg["qwen_api_key"],
            cfg.get("qwen_model") or "qwen-plus",
        )
    if slug == "qwen_vl" and cfg.get("qwen_api_key"):
        return (
            cfg["qwen_base_url"],
            cfg["qwen_api_key"],
            cfg.get("qwen_vl_model") or settings_svc.QWEN_VL_DEFAULT_MODEL,
        )
    if slug == "kimi" and cfg.get("kimi_api_key"):
        model = cfg.get("kimi_model") or settings_svc.KIMI_DEFAULT_MODEL
        return (cfg["kimi_base_url"], cfg["kimi_api_key"], model)
    if slug == "kimi_k3" and cfg.get("kimi_api_key"):
        model = cfg.get("kimi_k3_model") or settings_svc.KIMI_K3_DEFAULT_MODEL
        return (cfg["kimi_base_url"], cfg["kimi_api_key"], model)
    return None


CHAPTER_TEMPLATES = {
    "投标函": (
        "致：{tenderer}\n\n"
        "我方{bidder}（投标人）经认真研究「{project_name}」（招标编号：{tender_no}）招标文件，"
        "愿意按招标文件要求承担本项目维保服务，投标总价为{bid_amount}，工期/服务期为{duration}。"
        "我方承诺项目经理{project_manager}常驻现场，严格执行安全质量与保密制度，"
        "接受贵方监督检查，并保证所递交文件真实、有效。"
        "\n\n投标人：{bidder}\n日期：____年__月__日"
    ),
    "技术方案": (
        "针对「{project_name}」维保需求，我方拟采用“预防性维护+故障快速响应”技术路线。"
        "建立设备状态监测、备品备件保障、远程诊断与现场抢修联动机制，"
        "关键系统实行双人复核与工单闭环管理。服务期内按{tenderer}运行管理规定配合演练与验收，"
        "确保系统可用率满足招标要求，并形成可追溯的维保记录与月报。"
    ),
    "投标人简介": (
        "{bidder}系专业从事轨道交通智能化运维与机电维保的高新技术企业，"
        "具备相应资质与类似项目业绩，服务团队持证上岗。"
        "在「{project_name}」中将投入经验丰富的项目经理与技术人员，"
        "按{duration}服务期提供驻场与远程支持，确保响应时效与服务质量。"
    ),
    "资质与业绩说明": (
        "我方具备履行合同所需的法人资格、安全生产与质量管理体系认证，"
        "近年完成多项铁路及城市轨道交通机电维保项目，具备与本项目相匹配的业绩与人员储备。"
        "相关资质证书、业绩合同复印件及人员证书将按招标文件格式汇编，"
        "保证资料真实有效，接受{tenderer}核查。"
    ),
    "售后服务方案": (
        "服务期内提供 7×24 小时热线与 4 小时到场响应（市区），一般故障 24 小时内恢复。"
        "建立备件库与供应商绿色通道，重大故障启动应急预案并提交书面报告。"
        "质保期{warranty_period}，质保期满后继续提供有偿延保与升级服务，"
        "确保「{project_name}」系统长期稳定运行。"
    ),
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
    *,
    task_kind: str = "text",
) -> str:
    """调用外部 LLM；失败或无 Key 时返回空字符串，由上层走模板兜底。"""
    cfg = settings_svc.resolve_ai_config(db)
    kind = (task_kind or "text").strip().lower()

    if provider:
        slug_map = {
            "deepseek": "deepseek",
            "qwen": "qwen",
            "kimi": "kimi",
            "kimi_k3": "kimi_k3",
            "qwen_vl": "qwen_vl",
        }
        order = [slug_map.get(provider, provider)]
    else:
        order = pick_model(kind, cfg)

    single = len(order) == 1
    for slug in order:
        call = _provider_call(slug, cfg)
        if not call:
            continue
        base_url, api_key, model = call
        try:
            return await _openai_compat(base_url, api_key, model, messages)
        except Exception:
            if single:
                return ""
            continue
    return ""


async def _openai_compat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    *,
    vision: bool = False,
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: dict = {"model": model, "messages": messages, "temperature": 0.4}
    if vision:
        payload["temperature"] = 0.2
    async with httpx.AsyncClient(timeout=90 if vision else 60) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def _openai_compat_stream(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
) -> AsyncIterator[str]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: dict = {"model": model, "messages": messages, "temperature": 0.4, "stream": True}
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                text = delta.get("content") or ""
                if text:
                    yield text


async def chat_completion_stream(
    messages: list[dict],
    db: Session | None = None,
    *,
    task_kind: str = "text",
) -> AsyncIterator[str]:
    """流式输出 assistant 文本 token；无 Key 时无 yield。"""
    cfg = settings_svc.resolve_ai_config(db)
    kind = (task_kind or "text").strip().lower()
    order = pick_model(kind, cfg)
    for slug in order:
        call = _provider_call(slug, cfg, vision=False)
        if not call:
            continue
        base_url, api_key, model = call
        started = False
        try:
            async for tok in _openai_compat_stream(base_url, api_key, model, messages):
                started = True
                yield tok
            return
        except Exception:
            if started:
                raise
            continue


async def chat_completion_vision(
    messages: list[dict],
    *,
    image_data_urls: list[str] | None = None,
    db: Session | None = None,
) -> str:
    """多模态对话：优先 DeepSeek Flash，其次千问 VL / Kimi K3。"""
    imgs = [u for u in (image_data_urls or []) if u]
    if not imgs:
        return await chat_completion(messages, db=db, task_kind="text")

    cfg = settings_svc.resolve_ai_config(db)
    if not settings_svc.multimodal_ready(cfg):
        raise MultimodalRequiredError()

    user_content: list[dict] = []
    for m in messages:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            user_content.append({"type": "text", "text": m["content"]})
            break
    for url in imgs[:3]:
        user_content.append({"type": "image_url", "image_url": {"url": url}})

    vision_messages = [m for m in messages if m.get("role") != "user"]
    vision_messages.append({"role": "user", "content": user_content})

    for slug in pick_model("vision", cfg):
        call = _provider_call(slug, cfg, vision=True)
        if not call:
            continue
        base_url, api_key, model = call
        try:
            return await _openai_compat(
                base_url, api_key, model, vision_messages, vision=True,
            )
        except Exception:
            continue
    return ""


def local_chapter_text(chapter_key: str, fields: dict) -> str:
    tpl = CHAPTER_TEMPLATES.get(chapter_key)
    if not tpl:
        return (
            f"关于「{fields.get('project_name', '本项目')}」的{chapter_key}内容："
            f"投标人{fields.get('bidder', '')}将严格按照招标文件及行业规范组织实施，"
            f"确保工期{fields.get('duration', '')}、质量与安全目标全面达成。"
        )
    bidder = fields.get("bidder") or fields.get("bidder_name") or ""
    safe = {k: fields.get(k, "") or "" for k in (
        "project_name", "tender_no", "tenderer",
        "bid_amount", "duration", "project_manager", "warranty_period",
    )}
    safe["bidder"] = bidder
    try:
        return tpl.format(**safe)
    except Exception:
        return tpl


async def generate_chapter(
    chapter_key: str,
    fields: dict,
    db: Session | None = None,
    company_context: str = "",
    template_reference: str = "",
) -> dict:
    style = (
        "正式严谨，符合铁路/轨道交通行业规范；禁止口语化；"
        "数字、日期、金额须前后一致；全面响应招标要求。"
    )
    ctx = (company_context or "")[:2500]
    tpl_ctx = (template_reference or "")[:4500]
    ref_block = f"\n模板编写规则与参考正文：\n{tpl_ctx}\n" if tpl_ctx else ""
    prompt = (
        f"你是铁路行业标书撰写助手。请为章节「{chapter_key}」撰写正式、严谨的中文段落，"
        f"约200-400字。\n文风要求：{style}\n企业背景：{ctx}\n项目信息：{fields}。"
        f"{ref_block}"
        f"不要使用口语，不要编造无法核实的资质编号。"
        f"{'请严格遵循模板参考中的编写规则与格式要求。' if tpl_ctx else ''}"
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


def _score_faq_match(question: str, item: dict) -> float:
    q = question.strip()
    if not q:
        return 0.0
    iq = item.get("question") or ""
    ia = item.get("answer") or ""
    ic = item.get("category") or ""
    corpus = f"{iq}{ia}{ic}"

    # 领域关键词重合优先于单字重叠，避免「你是谁」误命中「审计报告」类 FAQ
    domain_words = [
        "资质", "业绩", "项目经理", "建造师", "审计", "行贿", "安全", "地铁", "铁路",
        "财务", "证书", "社保", "注册资金", "投标", "招标",
    ]
    keyword_hits = sum(1 for w in domain_words if w in q and w in corpus)
    if keyword_hits:
        return 0.25 + 0.2 * keyword_hits

    q_chars = {c for c in q if not c.isspace() and c not in "，。！？、；：""''（）【】"}
    i_chars = {c for c in iq if not c.isspace() and c not in "，。！？、；：""''（）【】"}
    if len(q_chars) < 4:
        return 0.0
    overlap = len(q_chars & i_chars) / max(len(q_chars), 1)
    if overlap < 0.45:
        return 0.0
    return overlap


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
        score = _score_faq_match(q, item)
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

    if best and best_score > 0.35:
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
        {
            "role": "system",
            "content": (
                "你是标书智能体助手，兼具基础对话与企业投标问答能力。"
                "当用户闲聊、询问你的身份或能力时，请自然介绍自己并说明可协助的标书编写、"
                "模板工程化、资质检索等功能；不要编造企业事实。"
                "当用户询问具体企业资质/业绩时，若资料不足请说明需人工核实。"
                "当用户提供本机文件夹绝对路径（如 C:\\\\Users\\\\...）并要求读取、录入、导入或落库时，"
                "不要回答「无法访问本地目录」——桌面版后端会代为读盘；"
                "应引导用户使用 📁 选择文件夹或确认导入卡片。"
            ),
        },
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


async def detect_placeholder_candidates(
    document_text: str,
    field_defs: list[dict],
    db: Session | None = None,
) -> list[dict]:
    """使用 LLM 从标书正文中识别可替换为占位符的原文片段。"""
    import json

    if not document_text.strip() or not field_defs:
        return []

    catalog = json.dumps(field_defs[:100], ensure_ascii=False)
    prompt = (
        "你是铁路/轨道交通行业标书模板工程化专家。"
        "请分析文档正文，找出应替换为模板占位符的具体原文片段。\n\n"
        f"可用字段目录（key 优先从中选择）：\n{catalog}\n\n"
        f"文档正文（节选）：\n{document_text[:14000]}\n\n"
        "识别规则（务必遵守）：\n"
        "1. original_text 必须是文档中可精确搜索的连续原文，优先较长片段，禁止 Word 域代码（如 PAGE \\*、TOC、HYPERLINK）\n"
        "2. tender_no 仅用于「招标编号/项目编号/采购编号」语境，不要把页码、包件序号、表格序号、型号编号一律标为 tender_no\n"
        "3. package_no 用于包件号/标段号；project_name 用于完整项目名称\n"
        "4. bid_date/sign_date 用于确定日期（如 2025年7月1日）；duration 用于工期/供货期（如 90日历天、6个月），不要混淆\n"
        "5. 金额用 bid_amount；电话 phone；邮编 postcode；法人 legal_name\n"
        "6. 若原文更适合资质材料插入位，bind_type 设为 qual 并给出 key=qual_<id>（若目录无则 bind_type=field）\n"
        "7. 若需立项时临场决策填写，bind_type=runtime，key=runtime_custom 或建议新 key\n"
        "8. 识别待填空白：冒号/标签后的下划线或空行（如「委托期限：____」「竞标人名称：」）、签字区「（签字）」、盖章「（盖单位章）」、日期占位「年 月 日」、表格空单元格\n"
        "9. 返回 JSON 数组，每项含 key, field_name, original_text, confidence(0-1), reason, bind_type, value_type(日期/工期/金额/文本)\n"
        "10. 只返回 JSON，不要 markdown；最多 30 项"
    )
    raw = await chat_completion([
        {"role": "system", "content": "你是标书模板工程化助手，只输出合法 JSON 数组。"},
        {"role": "user", "content": prompt},
    ], db=db)
    if not raw:
        return []
    from app.services.template_detect import parse_llm_candidate_json
    return parse_llm_candidate_json(raw)


async def resolve_placeholder_mappings(
    candidates: list[dict],
    resource_catalog: dict,
    document_text: str = "",
    db: Session | None = None,
) -> list[dict]:
    """结合系统字段/资质/企业档案目录，为候选原文二次决策映射目标。"""
    import json

    if not candidates:
        return []

    fields = (resource_catalog.get("fields") or [])[:80]
    quals = (resource_catalog.get("qualifications") or [])[:40]
    runtime = resource_catalog.get("runtime") or []
    compact_fields = [
        {k: v for k, v in item.items() if k in ("key", "name", "field_type", "module", "required")}
        for item in fields
    ]
    compact_quals = [
        {k: v for k, v in item.items() if k in ("id", "key", "name", "category", "keywords", "section_hint")}
        for item in quals
    ]
    payload = json.dumps(candidates[:40], ensure_ascii=False)
    prompt = (
        "你是标书模板工程化映射专家。请为下列「原文片段」选择最合适的系统字段或材料绑定。\n\n"
        f"字段定义目录：\n{json.dumps(compact_fields, ensure_ascii=False)}\n\n"
        f"资质材料目录：\n{json.dumps(compact_quals, ensure_ascii=False)}\n\n"
        f"临场填写选项：\n{json.dumps(runtime, ensure_ascii=False)}\n\n"
        f"待映射候选：\n{payload}\n\n"
        f"文档上下文（节选）：\n{document_text[:6000]}\n\n"
        "决策规则：\n"
        "1. 保留 original_text 不变；为每项输出最终 key、field_name、bind_type(field|qual|runtime)、confidence、reason\n"
        "2. tender_no 仅用于招标编号语境；日期用 bid_date；工期用 duration；不要滥用 tender_no\n"
        "3. 资质章节中的证照名称优先 bind_type=qual 并填 qualification_id\n"
        "4. 无合适字段时 bind_type=runtime，并给出 suggested_field{name,key,field_type,module}\n"
        "5. 返回与候选数量相同的 JSON 数组，只输出 JSON"
    )
    raw = await chat_completion([
        {"role": "system", "content": "你是标书映射决策助手，只输出合法 JSON 数组。"},
        {"role": "user", "content": prompt},
    ], db=db)
    if not raw:
        return candidates
    from app.services.template_detect import parse_resolve_json
    resolved = parse_resolve_json(raw)
    if not resolved:
        return candidates
    by_text = {(r.get("original_text") or "").strip(): r for r in resolved if r.get("original_text")}
    merged = []
    for c in candidates:
        ot = (c.get("original_text") or "").strip()
        hit = by_text.get(ot)
        if hit:
            item = {**c, **hit, "source": c.get("source", "ai"), "resolved_by_ai": True}
            if hit.get("bind_type") == "qual" and hit.get("qualification_id"):
                item["qualification_id"] = hit["qualification_id"]
            merged.append(item)
        else:
            merged.append(c)
    return merged


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
                cfg.get("deepseek_model") or settings_svc.DEEPSEEK_DEFAULT_MODEL,
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
    if provider == "qwen_vl":
        if not cfg.get("qwen_api_key"):
            return {"ok": False, "message": "未配置通义千问 API Key（VL 共用同一 Key）"}
        try:
            text = await _openai_compat(
                cfg["qwen_base_url"],
                cfg["qwen_api_key"],
                cfg.get("qwen_vl_model") or settings_svc.QWEN_VL_DEFAULT_MODEL,
                [{"role": "user", "content": "请只回复：ok"}],
            )
            return {"ok": True, "message": "通义千问 VL 连接成功", "sample": (text or "")[:80]}
        except Exception as e:
            return {"ok": False, "message": f"通义千问 VL 连接失败：{e}"}
    if provider == "kimi":
        if not cfg.get("kimi_api_key"):
            return {"ok": False, "message": "未配置 Kimi API Key"}
        try:
            text = await _openai_compat(
                cfg["kimi_base_url"],
                cfg["kimi_api_key"],
                cfg.get("kimi_model") or settings_svc.KIMI_DEFAULT_MODEL,
                [{"role": "user", "content": "请只回复：ok"}],
            )
            return {"ok": True, "message": "Kimi 文本连接成功", "sample": (text or "")[:80]}
        except Exception as e:
            return {"ok": False, "message": f"Kimi 连接失败：{e}"}
    if provider == "kimi_k3":
        if not settings_svc.kimi_k3_ready(cfg):
            return {"ok": False, "message": "未配置 Kimi K3（需 API Key 与 K3 模型）"}
        try:
            text = await _openai_compat(
                cfg["kimi_base_url"],
                cfg["kimi_api_key"],
                cfg.get("kimi_k3_model") or settings_svc.KIMI_K3_DEFAULT_MODEL,
                [{"role": "user", "content": "请只回复：ok"}],
            )
            return {"ok": True, "message": "Kimi K3 连接成功", "sample": (text or "")[:80]}
        except Exception as e:
            return {"ok": False, "message": f"Kimi K3 连接失败：{e}"}
    return {"ok": False, "message": "未知供应商"}
