#!/usr/bin/env python3
"""生成标书智能体系统参考材料（基于和远智能真实参考资料）。"""
from pathlib import Path
from datetime import date, timedelta
import shutil
import sys

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent / "sample_data"
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from heyuan_template_content import (  # noqa: E402
    AI_CHAPTERS,
    COMPANY,
    HISTORY_PROJECTS,
    build_engineered_template,
    build_history_document,
)


def write_txt(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def write_xlsx(path: Path, headers: list, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


def _save_doc(doc, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)


def make_simple_docx(path: Path, title: str, body: str):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    doc = Document()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(16)
    for line in body.strip().split("\n"):
        doc.add_paragraph(line)
    _save_doc(doc, path)


def export_engineered_templates() -> None:
    """同步输出到 customer_data，供 prefer_customer_pack 导入路径使用。"""
    out_dir = ROOT.parent / "customer_data" / "heyuanzhineng_20260729" / "engineered_templates"
    out_dir.mkdir(parents=True, exist_ok=True)
    tpl_dir = ROOT / "02_Word标书模板" / "标准投标Word模板"
    for name in sorted(tpl_dir.glob("*.docx")):
        dest = out_dir / name.name
        if name.resolve() != dest.resolve():
            shutil.copy2(name, dest)


def main():
    # 00
    write_txt(
        ROOT / "00_材料清单与说明" / "材料缺失说明.txt",
        "本次无缺失材料（模拟数据）。",
    )
    write_xlsx(
        ROOT / "00_材料清单与说明" / "材料提交清单.xlsx",
        ["序号", "目录路径", "文件名", "材料类型", "是否必填", "是否已提供", "备注"],
        [
            [1, "02_Word标书模板/标准投标Word模板/", "铁路工程投标模板1-工程化.docx", "Word模板", "必填", "是", "电气火灾监控类"],
            [2, "02_Word标书模板/标准投标Word模板/", "铁路工程投标模板3-工程化.docx", "Word模板", "必填", "是", "RTU及能管系统类"],
            [3, "03_历史投标文件/完整历史标书/", "历史标书-地铁12号线电气火灾监控-2025.docx", "历史标书", "必填", "是", ""],
            [3, "04_结构化字段与录入规范/", "标书关键字段清单.xlsx", "字段清单", "必填", "是", ""],
            [4, "05_条目完整性校验清单/", "商务标条目清单.xlsx", "条目清单", "必填", "是", ""],
            [5, "06_资质数据库参考材料/", "资质材料清单.xlsx", "资质清单", "必填", "是", ""],
            [6, "07_企业问答Chatbot参考/", "招标常见问题与标准答案.xlsx", "FAQ", "必填", "是", ""],
        ],
    )

    # 01
    write_txt(
        ROOT / "01_企业与项目基础信息" / "企业基本信息.txt",
        f"""
企业全称：{COMPANY['full_name']}
企业简称：{COMPANY['short_name']}
统一社会信用代码：{COMPANY['credit_code']}
注册地址：{COMPANY['address']}
办公地址：{COMPANY['address']}
法定代表人：{COMPANY['legal_name']}
注册资本：{COMPANY['registered_capital']}
成立日期：2011年3月10日
联系电话：{COMPANY['phone']}
企业邮箱：{COMPANY['email']}
开户银行：{COMPANY['bank_name']}
银行账号：37001618819050149538
企业简介：和远智能是中国高铁安全运行智能化产品的长期供应商，产品应用于全国3000余站点，具备轨道交通供电智能化全生命周期服务能力。
主营业务：综合能效管控、智能终端、工业互联网及物联网相关软、硬件产品研发、生产及销售
铁路/轨道交通相关资质概述：电子与智能化专业承包壹级、承装（修、试）电力设施三级、CMMI-L5、CRCC认证等
""",
    )
    docs_typical = ROOT.parent / "docs" / "标书智能体参考资料-和远智能-20260729" / "01-企业与项目基础信息" / "2.典型投标项目说明【建议】.txt"
    if docs_typical.exists():
        shutil.copy2(docs_typical, ROOT / "01_企业与项目基础信息" / "典型投标项目说明.txt")
    else:
        write_txt(
            ROOT / "01_企业与项目基础信息" / "典型投标项目说明.txt",
            "类别：电力远动RTU、接触网、电气火灾监控、能源管理系统等铁路四电物资采购项目。",
        )

    # 02 — 和远智能工程化模板（三卷式 + AI 章节）
    tpl_dir = ROOT / "02_Word标书模板" / "标准投标Word模板"
    _save_doc(
        build_engineered_template("铁路工程投标模板（电气火灾监控类）", [], AI_CHAPTERS),
        tpl_dir / "铁路工程投标模板1-工程化.docx",
    )
    _save_doc(
        build_engineered_template(
            "铁路工程投标模板（RTU及能管系统类）",
            [("物资品种", "material_type")],
            AI_CHAPTERS,
        ),
        tpl_dir / "铁路工程投标模板3-工程化.docx",
    )
    _save_doc(
        build_engineered_template("骨架模板-通用", [], AI_CHAPTERS),
        tpl_dir / "骨架模板-通用.docx",
    )
    write_xlsx(
        ROOT / "02_Word标书模板" / "模板占位符说明.xlsx",
        ["占位符名称", "含义", "示例值", "出现位置"],
        [
            ["{{project_name}}", "项目名称", "北京地铁12号线电气火灾监控采购", "封面、正文"],
            ["{{tender_no}}", "招标编号", "EEBWTP2026-120（1）", "封面"],
            ["{{package_no}}", "包件号", "DLZM08", "封面"],
            ["{{tenderer}}", "采购人", "中铁电气化局集团有限公司城铁公司", "封面、投标函"],
            ["{{bidder_name}}", "投标人", "和远智能科技股份有限公司", "封面"],
            ["{{bid_amount_upper}}", "投标总价大写", "人民币壹仟贰佰捌拾万元整", "报价部分"],
            ["{{bid_amount_lower}}", "投标总价小写", "12800000.00", "报价部分"],
            ["{{project_manager}}", "项目经理", "张方恒", "人员部分"],
            ["{{material_type}}", "物资品种", "RTU及能管系统", "模板3专用"],
        ],
    )
    write_txt(
        ROOT / "02_Word标书模板" / "模板格式规范说明.txt",
        """
正文：宋体 小四 1.5倍行距
一级标题：黑体 三号
二级标题：黑体 四号
页边距：上下2.54cm 左右3.17cm
""",
    )

    # 03 — 真实项目历史标书（和远智能参考资料）
    hist_dir = ROOT / "03_历史投标文件" / "完整历史标书"
    for proj in HISTORY_PROJECTS:
        _save_doc(build_history_document(proj), hist_dir / proj["filename"])
    write_txt(
        ROOT / "03_历史投标文件" / "历史标书章节结构说明.txt",
        """
第一卷 商务标
  第一章 投标函
  第二章 法定代表人身份证明
  第三章 授权委托书
  第四章 投标保证金
第二卷 技术标
  第一章 工程概况
  第二章 施工组织设计
  第三章 人员配置
  第四章 质量与安全保证措施
第三卷 报价标
  第一章 投标报价表
""",
    )
    write_txt(
        ROOT / "03_历史投标文件" / "AI生成内容风格参考.txt",
        """
语言风格：正式、严谨、符合铁路行业规范用语。
禁止使用：口语化表达、夸张修饰。
技术方案部分：需包含施工工艺、质量控制、安全措施等固定模块。
优秀段落样例：
本工程采用分段流水施工组织方式，关键控制节点包括路基填筑、桥梁架设、轨道铺设及联调联试。
""",
    )

    # 04
    write_xlsx(
        ROOT / "04_结构化字段与录入规范" / "标书关键字段清单.xlsx",
        ["字段名称", "字段英文名", "字段类型", "是否必填", "默认值", "校验规则", "所属模块", "备注"],
        [
            ["项目名称", "project_name", "文本", "是", "", "不超过200字", "封面", ""],
            ["招标编号", "tender_no", "文本", "是", "", "", "封面", ""],
            ["包件号", "package_no", "文本", "是", "", "", "封面", ""],
            ["采购人", "tenderer", "文本", "是", "", "", "报价函", ""],
            ["投标人", "bidder_name", "文本", "是", "和远智能科技股份有限公司", "", "封面", ""],
            ["投标总价大写", "bid_amount_upper", "文本", "是", "", "", "报价", ""],
            ["投标总价小写", "bid_amount_lower", "金额", "是", "", "大于0", "报价", ""],
            ["项目经理", "project_manager", "人员", "是", "张方恒", "", "人员", ""],
            ["物资品种", "material_type", "文本", "否", "RTU及能管系统", "", "封面", "模板3"],
        ],
    )
    write_xlsx(
        ROOT / "04_结构化字段与录入规范" / "下拉选项枚举值.xlsx",
        ["字段名称", "可选值（多个值用中文分号分隔）"],
        [
            ["项目类型", "铁路工程;轨道交通;站房建设;线路维护;其他"],
            ["招标方式", "公开招标;邀请招标;竞争性谈判"],
            ["资质等级", "特级;一级;二级"],
        ],
    )
    write_txt(
        ROOT / "04_结构化字段与录入规范" / "铁路行业专用术语表.txt",
        """
TB 10401 《铁路工程施工质量验收标准》
TB 10301 《铁路工程设计技术规范》
联调联试：工程完工后对信号、供电、轨道等系统进行综合调试。
""",
    )

    # 05
    write_xlsx(
        ROOT / "05_条目完整性校验清单" / "商务标条目清单.xlsx",
        ["序号", "条目名称", "是否必含", "对应章节", "备注"],
        [
            [1, "投标函", "必含", "第一章", ""],
            [2, "法定代表人身份证明", "必含", "第二章", ""],
            [3, "授权委托书", "必含", "第三章", ""],
            [4, "投标保证金凭证", "必含", "第四章", ""],
            [5, "联合体协议书", "条件必含", "第五章", "仅联合体投标时"],
        ],
    )
    write_xlsx(
        ROOT / "05_条目完整性校验清单" / "技术标条目清单.xlsx",
        ["序号", "条目名称", "是否必含", "对应章节", "备注"],
        [
            [1, "工程概况", "必含", "第一章", ""],
            [2, "施工组织设计", "必含", "第二章", ""],
            [3, "人员配置", "必含", "第三章", ""],
            [4, "质量与安全保证措施", "必含", "第四章", ""],
            [5, "工期保障措施", "必含", "第五章", ""],
        ],
    )
    write_xlsx(
        ROOT / "05_条目完整性校验清单" / "报价标条目清单.xlsx",
        ["序号", "条目名称", "是否必含", "对应章节", "备注"],
        [
            [1, "投标报价表", "必含", "第一章", ""],
            [2, "分项报价", "必含", "第二章", ""],
            [3, "主要材料价格表", "建议", "第三章", ""],
        ],
    )
    write_xlsx(
        ROOT / "05_条目完整性校验清单" / "资质材料必附清单.xlsx",
        ["序号", "资质名称", "所属分类", "适用项目类型", "是否必附", "备注"],
        [
            [1, "营业执照", "企业资质包", "全部", "必附", ""],
            [2, "铁路工程专业承包资质", "企业资质包", "铁路工程", "必附", ""],
            [3, "近3年类似业绩", "业绩包", "全部", "必附", "至少3个"],
            [4, "项目经理一级建造师证", "人员信息包", "全部", "必附", ""],
            [5, "近三年审计报告", "财务信息包", "全部", "必附", ""],
        ],
    )

    # 06 资质
    qual_root = ROOT / "06_资质数据库参考材料"
    today = date.today()
    quals = [
        ("01_企业资质包", "营业执照", "企业资质_营业执照_长期.docx", True, "市场监督管理局"),
        ("01_企业资质包", "电子与智能化工程专业承包壹级", "企业资质_电子智能化壹级_20291219.docx", False, "住建部"),
        ("01_企业资质包", "安全生产许可证", "企业资质_安全生产许可证_20290604.docx", False, "应急管理部门"),
        ("02_业绩包", "地铁12号线电气火灾监控中标", "业绩_地铁12号线中标通知_2025.docx", True, "中铁电气化局"),
        ("02_业绩包", "龙烟铁路RTU采购合同", "业绩_龙烟铁路RTU合同_2024.docx", True, "中铁四局电气化公司"),
        ("03_人员信息包", "项目经理张方恒简历", "人员_项目经理张方恒.docx", False, "企业内部"),
        ("03_人员信息包", "技术负责人职称证", "人员_技术负责人职称.docx", False, "人社部门"),
        ("04_财务信息包", "近三年审计报告", "财务_近三年审计报告_2025.docx", True, "会计师事务所"),
        ("05_信誉与法律包", "无行贿犯罪证明", "信誉_无行贿证明_2026.docx", False, "检察机关"),
        ("06_技术方案包", "施工组织设计模板", "技术_施工组织设计模板.docx", True, "企业内部"),
        ("07_商务文件包", "投标函模板", "商务_投标函模板.docx", True, "企业内部"),
        ("07_商务文件包", "授权委托书模板", "商务_授权委托书模板.docx", True, "企业内部"),
    ]
    rows = []
    for i, (cat, name, fname, long_term, issuer) in enumerate(quals, 1):
        expire = "" if long_term else (today + timedelta(days=365 * (2 if "2030" in fname else 1))).isoformat()
        start = (today - timedelta(days=365)).isoformat()
        make_simple_docx(
            qual_root / cat / fname,
            name,
            f"材料名称：{name}\n颁发机构：{issuer}\n有效期起：{start}\n有效期止：{expire or '长期有效'}\n（模拟材料，仅供系统开发测试）",
        )
        rows.append([
            i, cat.split("_", 1)[1], name, fname, start, expire or "长期",
            issuer, "docx", name, "是" if long_term else "否", "模拟材料",
        ])
    write_xlsx(
        qual_root / "资质材料清单.xlsx",
        ["序号", "分类", "材料名称", "文件名", "有效期起", "有效期止", "颁发机构", "文件类型", "关键词标签", "是否长期有效", "备注"],
        rows,
    )
    write_txt(
        qual_root / "资质插入规则说明.txt",
        """
企业资质章节 → 营业执照 + 铁路工程施工总承包资质 + 安全生产许可证
人员章节 → 项目经理建造师证 + 简历
业绩章节 → 类似项目合同 + 中标通知书
商务部分 → 投标函模板 + 授权委托书模板
""",
    )

    # 07 FAQ
    write_xlsx(
        ROOT / "07_企业问答Chatbot参考" / "招标常见问题与标准答案.xlsx",
        ["序号", "问题类别", "问题内容", "标准答案", "答案来源材料", "备注"],
        [
            [1, "企业资质类", "贵公司是否具备电子与智能化工程专业承包壹级资质？",
             "是，我公司具备电子与智能化工程专业承包壹级资质。", "企业资质_电子智能化壹级_20291219.docx", ""],
            [2, "业绩类", "近5年是否有类似铁路四电项目业绩？",
             "有，我公司完成北京地铁12号线电气火灾监控、龙烟市域铁路RTU采购等多项类似业绩。", "业绩_地铁12号线中标通知_2025.docx", ""],
            [3, "人员类", "拟任项目经理是否具备相关资历？",
             "是，拟任项目经理张方恒具备丰富轨道交通四电项目供货与调试经验。", "人员_项目经理张方恒.docx", ""],
            [4, "财务类", "是否可提供近三年审计报告？",
             "可以，我公司可提供近三年完整审计报告。", "财务_近三年审计报告_2025.docx", ""],
            [5, "信誉类", "近三年是否有行贿犯罪记录？",
             "无，我公司可提供无行贿犯罪记录证明。", "信誉_无行贿证明_2026.docx", ""],
            [6, "技术类", "施工组织设计包含哪些主要内容？",
             "包含工程概况、施工部署、进度计划、质量与安全保证措施等。", "技术_施工组织设计模板.docx", ""],
            [7, "企业资质类", "是否持有安全生产许可证？",
             "是，我公司持有有效期内的安全生产许可证。", "企业资质_安全生产许可证_20281231.docx", ""],
            [8, "业绩类", "是否有城市轨道交通项目经验？",
             "有，我公司完成北京地铁12号线电气火灾监控设备采购项目。", "业绩_地铁12号线中标通知_2025.docx", ""],
        ],
    )
    write_txt(
        ROOT / "07_企业问答Chatbot参考" / "招标文件常见要求摘录.txt",
        """
常见评分点：类似业绩、项目经理资质、施工组织设计完整性、财务状况、信誉情况。
常见硬性要求：铁路工程施工总承包一级、安全生产许可证、无重大安全事故声明。
""",
    )

    # 清理旧版简易模板
    obsolete_tpl = tpl_dir / "铁路工程投标模板_通用版.docx"
    if obsolete_tpl.exists():
        obsolete_tpl.unlink()
    hist_dir = ROOT / "03_历史投标文件" / "完整历史标书"
    for old in (
        "历史标书_XX站房改造_2025.docx",
        "历史标书_京沪高铁XX段_2024.docx",
        "历史标书_地铁XX号线_2023.docx",
    ):
        p = hist_dir / old
        if p.exists():
            p.unlink()

    export_engineered_templates()
    print(f"参考材料已生成至: {ROOT}")
    print("工程化模板已同步至 customer_data/heyuanzhineng_20260729/engineered_templates/")


if __name__ == "__main__":
    main()
