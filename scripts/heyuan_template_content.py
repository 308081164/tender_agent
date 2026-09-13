"""和远智能参考材料驱动的标书模板/历史标书内容定义（供 sample_data 与客户包生成）。"""
from __future__ import annotations

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

# —— 企业信息（来源：docs/标书智能体参考资料-和远智能-20260729/01-企业与项目基础信息）——
COMPANY = {
    "full_name": "和远智能科技股份有限公司",
    "short_name": "和远智能",
    "credit_code": "91370100568119776D",
    "address": "济南市高新区新泺大街1166号奥盛大厦1号楼7层",
    "legal_name": "张方恒",
    "registered_capital": "5270万元",
    "phone": "0531-68621770",
    "fax": "0531-68621679",
    "website": "www.hyzn77.com",
    "postcode": "250100",
    "bank_name": "中国建设银行股份有限公司济南黄金时代支行",
    "email": "heyuanswb@163.com",
}

AI_CHAPTERS = [
    "技术规格书条款点对点应答",
    "生产供应计划方案",
    "运输方案",
    "售后服务方案",
    "应急预案和配套措施",
    "质量保证措施",
]

# 模板1：电气火灾监控类（参考北京地铁12号线项目）
TPL1_SAMPLE = {
    "project_name": (
        "北京地铁12号线工程合建柳芳110千伏轨道交通共建变电站总承包项目"
        "电气火灾监控设备、矿物质电缆及附件包件二次采购"
    ),
    "tenderer": "中铁电气化局集团有限公司城铁公司",
    "tender_no": "EEBWTP2026-120（1）",
    "package_no": "DLZM08",
    "bid_amount_upper": "人民币壹仟贰佰捌拾万元整",
    "bid_amount_lower": "12800000.00",
}

# 模板3：RTU及能管系统类（参考龙烟市域铁路项目）
TPL3_SAMPLE = {
    "project_name": "中铁四局集团电气化工程有限公司龙烟市域铁路LYSG-2标四电项目RTU及能管系统采购",
    "tenderer": "中铁四局集团电气化工程有限公司",
    "tender_no": "ZTSJWZ-DQH-2025-041",
    "package_no": "DL-01",
    "material_type": "RTU及能管系统",
    "bid_amount_upper": "人民币玖佰陆拾万元整",
    "bid_amount_lower": "9600000.00",
}

HISTORY_PROJECTS = [
    {
        "filename": "历史标书-地铁12号线电气火灾监控-2025.docx",
        "title": "投标文件",
        "project": TPL1_SAMPLE["project_name"],
        "tender_no": "EEBWTP2026-120（1）",
        "tenderer": TPL1_SAMPLE["tenderer"],
        "amount_upper": "人民币壹仟贰佰伍拾万元整",
        "amount_lower": "12500000.00",
        "package_no": "DLZM08",
        "project_manager": "张方恒",
        "duration": "合同签订后90日历天内完成供货及安装调试",
    },
    {
        "filename": "历史标书-龙烟铁路RTU采购-2024.docx",
        "title": "投标文件",
        "project": TPL3_SAMPLE["project_name"],
        "tender_no": TPL3_SAMPLE["tender_no"],
        "tenderer": TPL3_SAMPLE["tenderer"],
        "amount_upper": "人民币玖佰伍拾万元整",
        "amount_lower": "9500000.00",
        "package_no": "DL-01",
        "project_manager": "张方恒",
        "duration": "合同签订后60日历天内完成供货",
    },
    {
        "filename": "历史标书-雄安至忻州高铁能源管理-2024.docx",
        "title": "投标文件",
        "project": "新建雄安新区至忻州高速铁路四电及相关工程XXQD标段远程抄表及能源管理系统采购",
        "tender_no": "XAXZ-2024-DQ-018",
        "tenderer": "中国铁路北京局集团有限公司",
        "amount_upper": "人民币柒佰捌拾万元整",
        "amount_lower": "7800000.00",
        "package_no": "NY-03",
        "project_manager": "张方恒",
        "duration": "180日历天",
    },
]


def _title_paragraph(doc: Document, text: str, size: int = 20) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(size)


def _add_volume_structure(doc: Document, ai_chapters: list[str]) -> None:
    doc.add_heading("第一卷 商务标", level=1)
    doc.add_heading("第一章 投标函", level=2)
    doc.add_paragraph(
        "致 {{tenderer}}：我方（{{bidder_name}}）已仔细研究"
        "「{{project_name}}」（招标编号：{{tender_no}}，包件号：{{package_no}}）"
        "招标文件的全部内容，愿意以 {{bid_amount_upper}}（小写：{{bid_amount_lower}}）"
        "的投标总价，按合同约定条件完成供货、安装调试及相关服务。"
    )
    doc.add_heading("第二章 法定代表人身份证明及授权委托书", level=2)
    doc.add_paragraph(
        "法定代表人：{{legal_name}}，职务：董事长。"
        "注册地址：{{address}}，邮编：{{postcode}}，电话：{{phone}}，传真：{{fax}}。"
    )
    doc.add_heading("第三章 投标人基本情况表", level=2)
    doc.add_paragraph("企业名称：{{bidder_name}}")
    doc.add_paragraph("注册资金：{{registered_capital}}")
    doc.add_paragraph("开户银行：{{bank_name}}")
    doc.add_paragraph("网址：{{website}}")
    doc.add_heading("第四章 投标保证金及商务偏差表", level=2)
    doc.add_paragraph("（按招标文件要求附投标保证金凭证及商务条款响应表）")

    doc.add_heading("第二卷 技术标", level=1)
    doc.add_heading("第一章 项目理解与总体方案", level=2)
    doc.add_paragraph(
        "本项目为 {{project_name}}，采购人为 {{tenderer}}。"
        "我方将依据招标文件技术规格书，提供符合铁路行业标准的设备与系统集成方案。"
    )
    for ch in ai_chapters:
        doc.add_heading(ch, level=2)
        doc.add_paragraph(f"【AI_GENERATED:{ch}】")

    doc.add_heading("第三卷 报价标", level=1)
    doc.add_heading("第一章 投标报价汇总表", level=2)
    doc.add_paragraph("投标总价（大写）：{{bid_amount_upper}}")
    doc.add_paragraph("投标总价（小写）：{{bid_amount_lower}}")
    doc.add_heading("第二章 分项报价及说明", level=2)
    doc.add_paragraph("（分项报价表见附件，单价、合价与投标总价保持一致）")


def build_engineered_template(
    title: str,
    extra_fields: list[tuple[str, str]],
    ai_chapters: list[str] | None = None,
) -> Document:
    """生成工程化 Word 模板（含 {{placeholder}} 与 AI 章节标记）。"""
    doc = Document()
    _title_paragraph(doc, title, 18)
    base_fields = [
        ("项目名称", "project_name"),
        ("招标编号/项目编号", "tender_no"),
        ("包件号", "package_no"),
        ("采购人", "tenderer"),
        ("投标人", "bidder_name"),
        ("投标总价（大写）", "bid_amount_upper"),
        ("投标总价（小写）", "bid_amount_lower"),
        ("日期", "bid_date"),
        ("地址", "address"),
        ("电话", "phone"),
        ("传真", "fax"),
        ("邮编", "postcode"),
        ("网址", "website"),
        ("法定代表人", "legal_name"),
        ("注册资金", "registered_capital"),
        ("开户银行", "bank_name"),
        ("项目经理", "project_manager"),
    ]
    seen = {k for _, k in base_fields}
    for label, key in extra_fields:
        if key not in seen:
            base_fields.append((label, key))
            seen.add(key)
    for label, key in base_fields:
        doc.add_paragraph(f"{label}：{{{{{key}}}}}")
    doc.add_page_break()
    _add_volume_structure(doc, ai_chapters or AI_CHAPTERS)
    return doc


def build_history_document(project: dict) -> Document:
    """生成完整历史标书（已填写真实项目信息，用于智能替换演示）。"""
    doc = Document()
    _title_paragraph(doc, "投标文件", 20)
    doc.add_paragraph(f"项目名称：{project['project']}")
    doc.add_paragraph(f"招标编号：{project['tender_no']}")
    doc.add_paragraph(f"包件号：{project.get('package_no', '')}")
    doc.add_paragraph(f"采购人：{project['tenderer']}")
    doc.add_paragraph(f"投标人：{COMPANY['full_name']}")
    doc.add_paragraph(f"投标总价：{project['amount_upper']}（{project['amount_lower']}）")
    doc.add_paragraph(f"供货/工期：{project['duration']}")
    doc.add_paragraph(f"项目经理：{project['project_manager']}")

    doc.add_heading("第一卷 商务标", level=1)
    doc.add_heading("第一章 投标函", level=2)
    doc.add_paragraph(
        f"致 {project['tenderer']}："
        f"我方 {COMPANY['full_name']} 愿以 {project['amount_upper']} "
        f"承接「{project['project']}」设备供货及相关服务，"
        f"工期/供货期 {project['duration']}，项目经理 {project['project_manager']}。"
    )
    doc.add_heading("第二章 法定代表人身份证明及授权委托书", level=2)
    doc.add_paragraph(
        f"法定代表人 {COMPANY['legal_name']}，注册地址 {COMPANY['address']}，"
        f"电话 {COMPANY['phone']}。已附法定代表人身份证明及授权委托书。"
    )
    doc.add_heading("第三章 投标人基本情况", level=2)
    doc.add_paragraph(f"企业全称：{COMPANY['full_name']}")
    doc.add_paragraph(f"统一社会信用代码：{COMPANY['credit_code']}")
    doc.add_paragraph(f"注册资本：{COMPANY['registered_capital']}")
    doc.add_paragraph(
        "企业简介：和远智能是中国高铁安全运行智能化产品的长期供应商，"
        "产品应用于全国3000余站点，具备轨道交通供电智能化全生命周期服务能力。"
    )

    doc.add_heading("第二卷 技术标", level=1)
    doc.add_heading("第一章 项目理解与总体方案", level=2)
    doc.add_paragraph(
        f"本项目为{project['project']}。我方将依据招标文件技术规格书，"
        "提供符合 TB/T 标准及行业规范的设备选型、系统集成与调试方案，"
        "确保与既有铁路供电监控系统兼容。"
    )
    doc.add_heading("第二章 技术规格书条款点对点应答", level=2)
    doc.add_paragraph(
        "我方对招标文件技术规格书全部条款进行逐项响应："
        "设备性能指标满足或优于招标要求；通信协议支持 IEC 60870-5-104；"
        "具备远程运维与事件记录功能；出厂前完成型式试验与第三方检测。"
    )
    doc.add_heading("第三章 生产供应与运输方案", level=2)
    doc.add_paragraph(
        "生产周期按合同节点排产，关键元器件采用原厂正品；"
        "运输采用防震防潮包装，到货后由项目经理组织开箱验收与联合调试。"
    )
    doc.add_heading("第四章 售后服务与质量保证", level=2)
    doc.add_paragraph(
        "质保期不少于24个月；7×24小时技术支持；"
        "建立三级质量检查体系，关键工序100%检验。"
    )

    doc.add_heading("第三卷 报价标", level=1)
    doc.add_heading("第一章 投标报价汇总表", level=2)
    doc.add_paragraph(f"投标总价：{project['amount_upper']}（{project['amount_lower']}）")
    doc.add_paragraph("分项报价详见报价附件，合价与总价一致。")

    return doc
