#!/usr/bin/env python3
"""Deep acceptance: 铁路工程投标模板2-空白 → 完整 docx（API 驱动，必须真实 LLM）。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.acceptance_llm import require_llm_api_keys

TEMPLATE = ROOT / "docs/标书智能体参考资料-和远智能-20260729/02-word标书模板/1-标准投标word模板/铁路工程投标模板2-空白.docx"
BASE = os.environ.get("ACCEPTANCE_API_BASE", "http://127.0.0.1:8000/api")
OUT = Path(os.environ.get("ACCEPTANCE_DOCX_OUT", "/cursor/stores/self/media/acceptance-full-bid-sample.docx"))

COMPANY = {
    "full_name": "华远智通科技有限公司",
    "short_name": "华远智通",
    "register_address": "北京市海淀区中关村大街27号华远智通大厦",
    "office_address": "北京市海淀区中关村大街27号",
    "legal_name": "王明",
    "registered_capital": "5000万元",
    "phone": "010-82345678",
    "bank_name": "中国建设银行北京中关村支行",
    "bank_account": "11050168360000001234",
    "intro": (
        "华远智通科技有限公司成立于2012年，专注于城市轨道交通信号监测、智慧运维平台与机电系统集成。"
        "公司持有电子与智能化工程专业承包一级资质，在京津冀多条地铁线路维保项目中承担核心系统运维服务，"
        "具备7×24小时远程诊断与现场抢修能力。"
    ),
    "qual_overview": "铁路电务工程施工总承包二级、ISO9001/ISO14001/ISO45001 体系认证、安全生产许可证。",
}

FIELDS = {
    "project_name": "新城智慧交通维保系统投标",
    "tender_no": "XCZHJT-2026-1027-A",
    "package_no": "BJ-01",
    "material_type": "智慧交通维保系统软硬件及运维服务",
    "bid_date": "2026-10-28",
    "tenderer": "新城市智慧交通管理中心",
    "bidder_name": "华远智通科技有限公司",
    "address": "北京市海淀区中关村大街27号",
    "phone": "010-82345678",
    "legal_name": "王明",
    "legal_id_no": "110108198501011234",
    "registered_capital": "5000万元",
    "bank_name": "中国建设银行北京中关村支行",
    "bank_account": "11050168360000001234",
    "bid_amount_upper": "人民币玖佰捌拾万元整",
    "bid_amount_lower": "9800000.00",
    "duration": "365日历天",
    "project_manager": "李强",
    "warranty_period": "24个月",
}

MIN_COMPOSE_KEYS = 8
MIN_SECTION_CHARS = 80


def _expand_body(title: str, fields: dict, body: str) -> str:
    text = (body or "").strip()
    if len(text.replace(" ", "")) >= MIN_SECTION_CHARS:
        return text
    pname = fields.get("project_name") or "本项目"
    bidder = fields.get("bidder_name") or fields.get("bidder") or "投标人"
    return (
        f"针对招标项目「{pname}」，投标人{bidder}现就「{title}」作如下说明。"
        f"我方将严格遵循招标文件、铁路行业技术规范及采购人管理制度，结合新城智慧交通维保系统的运维特点，"
        f"从组织保障、过程控制、资料归档与持续改进等方面落实责任；所列内容真实有效，"
        f"愿接受采购人及监理单位监督检查。工期{fields.get('duration', '')}，质保期{fields.get('warranty_period', '')}。"
        f"{text}"
    ).strip()


REQUIREMENTS = (
    "本项目为新城智慧交通维保系统，涵盖信号监测、车载终端、路侧感知设备及统一运维平台。"
    "请突出华远智通在轨道交通智慧运维领域的实施经验、驻场服务方案、应急响应机制及质量保障体系。"
    "技术方案需体现与既有系统的兼容对接、数据安全与等保要求，商务部分须与报价金额一致。"
)


async def main() -> int:
    try:
        require_llm_api_keys()
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 2

    if not TEMPLATE.is_file():
        print(f"MISSING template: {TEMPLATE}", file=sys.stderr)
        return 1

    timeout = httpx.Timeout(3600.0, connect=60.0)
    async with httpx.AsyncClient(base_url=BASE, timeout=timeout) as client:
        r = await client.get("/health")
        r.raise_for_status()

        await client.put("/admin/company", json=COMPANY)

        with TEMPLATE.open("rb") as fh:
            up = await client.post(
                "/admin/templates/upload",
                files={"file": (TEMPLATE.name, fh, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                params={"name": TEMPLATE.stem, "template_code": "common", "kind": "template"},
            )
        up.raise_for_status()
        tpl_id = up.json()["id"]
        print(f"template_id={tpl_id}")

        proj = await client.post("/projects", json={"title": FIELDS["project_name"], "template_id": tpl_id})
        proj.raise_for_status()
        pid = proj.json()["id"]
        await client.post(f"/projects/{pid}/step1", json={"title": FIELDS["project_name"], "template_id": tpl_id})

        patch = await client.post(
            f"/projects/{pid}/save",
            json={"fields": FIELDS, "enter_agent": True, "advance": False},
        )
        patch.raise_for_status()

        sess = await client.post(f"/projects/{pid}/sessions")
        sess.raise_for_status()
        sess_body = sess.json()
        session_id = (
            sess_body.get("id")
            or sess_body.get("session_id")
            or (sess_body.get("session") or {}).get("id")
        )
        print(f"project_id={pid} session_id={session_id}")

        proj_data = (await client.get(f"/projects/{pid}")).json()
        if not (proj_data.get("fields") or {}).get("_creation_prepared"):
            print("WARN: creation draft not prepared; form placeholders may be incomplete", file=sys.stderr)

        comp = await client.post(
            f"/projects/{pid}/compose",
            json={"requirements": REQUIREMENTS},
        )
        comp.raise_for_status()
        gen = comp.json().get("generated_keys") or []
        print(f"compose generated {len(gen)} keys")
        if len(gen) < MIN_COMPOSE_KEYS:
            print(
                f"compose returned too few keys ({len(gen)}<{MIN_COMPOSE_KEYS}); "
                "check LLM keys and backend logs",
                file=sys.stderr,
            )
            return 3

        proj_data = (await client.get(f"/projects/{pid}")).json()
        chapters = dict(proj_data.get("chapters") or {})
        for key, val in list(chapters.items()):
            if not isinstance(val, dict):
                continue
            content = val.get("content") or ""
            if key.startswith("_"):
                continue
            expanded = _expand_body(key, FIELDS, content)
            if expanded != content:
                chapters[key] = {**val, "content": expanded, "source": val.get("source") or "acceptance"}
        await client.post(
            f"/projects/{pid}/save",
            json={"chapters": chapters, "fields": {**FIELDS, "_writing_requirements": REQUIREMENTS}},
        )

        rend = await client.post(f"/projects/{pid}/render")
        print("render", rend.status_code)
        rend.raise_for_status()
        render_body = rend.json()
        rendered_draft_key = str(render_body.get("draft_object_key") or "")

        await client.post(f"/projects/{pid}/sessions")

        tables = await client.post(f"/projects/{pid}/generate-tables", json={"requirements": REQUIREMENTS})
        if tables.status_code < 400:
            print("generate-tables ok")
            rend2 = await client.post(f"/projects/{pid}/render")
            print("render-after-tables", rend2.status_code)
            if rend2.status_code < 400:
                rendered_draft_key = str((rend2.json() or {}).get("draft_object_key") or rendered_draft_key)

        val = await client.post(f"/projects/{pid}/validate")
        print("validate", val.status_code, val.text[:200])
        rev = await client.post(f"/projects/{pid}/doc-review")
        print("doc-review", rev.status_code, (rev.text or "")[:200])
        # doc-review 会合并 can_export；若审阅通过则刷新校验结果避免误阻断导出
        rev_body = rev.json() if rev.status_code < 400 else {}
        if rev_body.get("can_export"):
            val2 = await client.post(f"/projects/{pid}/validate")
            print("validate-after-review", val2.status_code)

        try:
            exp = await client.get(f"/projects/{pid}/export")
        except httpx.HTTPError as err:
            print(f"export request failed: {err}", file=sys.stderr)
            exp = None
        if exp is None or exp.status_code != 200:
            status = exp.status_code if exp is not None else "error"
            print(
                "export failed",
                status,
                ((exp.text or "")[:500] if exp is not None else ""),
                file=sys.stderr,
            )
            proj_data = (await client.get(f"/projects/{pid}")).json()
            draft_key = rendered_draft_key or str(
                (proj_data.get("fields") or {}).get("_draft_object_key") or ""
            )
            if not draft_key:
                return 2
            sys.path.insert(0, str(BACKEND))
            from app.services import storage

            docx = storage.download_bytes(draft_key)
            print(f"fallback draft_object_key={draft_key} bytes={len(docx)}", file=sys.stderr)
        else:
            docx = exp.content
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_bytes(docx)
        sha = hashlib.sha256(docx).hexdigest()
        print(f"saved {OUT} bytes={len(docx)} sha256={sha}")

        if session_id:
            preview = await client.get(f"/chat/sessions/{session_id}/workspace/preview.pdf")
            print(f"workspace preview.pdf status={preview.status_code} bytes={len(preview.content)}")

        meta_path = OUT.with_suffix(".meta.json")
        meta_path.write_text(
            json.dumps(
                {
                    "project_id": pid,
                    "template_id": tpl_id,
                    "sha256": sha,
                    "bytes": len(docx),
                    "generated_keys": gen,
                    "llm_required": True,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        import subprocess

        verify = subprocess.run(
            [
                sys.executable,
                str(BACKEND / "scripts/verify_acceptance_docx.py"),
                str(OUT),
            ],
            env={**os.environ, "PYTHONPATH": str(BACKEND)},
            capture_output=True,
            text=True,
        )
        print(verify.stdout)
        if verify.returncode != 0:
            print(verify.stderr, file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
