"""文档引擎 v2 编排入口。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.doc_engine.assembler import assemble_document
from app.services.doc_engine.composition import build_composition_plan, generate_block_contents
from app.services.doc_engine.manifest import get_manifest, set_manifest
from app.services.doc_engine.parser import enrich_snapshot_with_locations, parse_template_manifest
from app.services.doc_engine.replacement import build_image_bindings_from_quals
from app.services.doc_engine.review import review_document


async def analyze_template(
    docx_bytes: bytes,
    *,
    is_history: bool = False,
    field_defs: list[dict] | None = None,
) -> dict[str, Any]:
    manifest = parse_template_manifest(
        docx_bytes, is_history=is_history, field_defs=field_defs
    )
    return manifest


def attach_manifest_to_template(placeholders: dict | None, manifest: dict) -> dict:
    return set_manifest(placeholders, manifest)


async def render_project_document(
    docx_bytes: bytes,
    template_placeholders: dict | None,
    fields: dict[str, Any],
    chapters: dict[str, Any] | None,
    *,
    source_snapshot: dict | None = None,
    qual_files: list[dict] | None = None,
    highlight: bool = False,
    requirements: str = "",
    company_context: str = "",
    db: Session | None = None,
    mode: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """统一渲染：自动选择创作/替换/混合模式。"""
    manifest = get_manifest(template_placeholders)
    meta: dict[str, Any] = {"engine": "doc_engine_v2"}

    if not manifest:
        manifest = parse_template_manifest(docx_bytes, is_history=bool(source_snapshot))
        meta["manifest_auto"] = True

    doc_mode = mode or manifest.get("mode") or "hybrid"
    block_contents: dict[str, str] = {}

    # 创作模式：先生成块内容
    if doc_mode in ("create", "hybrid") and requirements:
        plan = await build_composition_plan(
            manifest, fields, requirements, company_context, db=db
        )
        block_contents = await generate_block_contents(
            plan, fields, requirements, company_context, db=db
        )
        meta["composition_plan"] = plan

    image_bindings = build_image_bindings_from_quals(
        manifest, qual_files or [], source_snapshot
    )
    meta["image_bindings"] = len(image_bindings)

    data = assemble_document(
        docx_bytes,
        manifest,
        fields,
        chapters,
        source_snapshot=source_snapshot,
        highlight=highlight,
        image_bindings=image_bindings,
        block_contents=block_contents,
    )

    # 未绑定到槽位的资质仍追加到文末（兼容 v1）
    if qual_files and not image_bindings:
        from app.services import word
        data = word.embed_qualifications(data, qual_files)

    meta["mode"] = doc_mode
    return data, meta


async def review_project_document(
    docx_bytes: bytes,
    template_placeholders: dict | None,
    fields: dict[str, Any],
    source_snapshot: dict | None,
    required_fields: list[str],
    db: Session | None = None,
) -> dict[str, Any]:
    manifest = get_manifest(template_placeholders)
    return await review_document(
        docx_bytes, fields, manifest, source_snapshot, required_fields, db=db
    )


def build_enriched_snapshot(
    docx_bytes: bytes,
    field_values: dict[str, str],
) -> dict[str, Any]:
    return enrich_snapshot_with_locations(docx_bytes, field_values)
