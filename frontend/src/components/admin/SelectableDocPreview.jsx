import React, { useMemo } from 'react'
import { renderPreviewBlock } from './DocxTextPreview'

export function findMappingForSelection(mappings, text) {
  const t = (text || '').trim()
  if (!t || !mappings?.length) return null

  const exact = mappings.find((m) => m.original_text === t)
  if (exact) return exact

  const phMatch = t.match(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/)
  if (phMatch) {
    const byKey = mappings.find((m) => m.key === phMatch[1])
    if (byKey) return byKey
  }

  const contains = mappings.find(
    (m) => m.original_text && (t.includes(m.original_text) || m.original_text.includes(t)),
  )
  return contains || null
}

export default function SelectableDocPreview({
  paragraphs = [],
  mappings = [],
  onSelectText,
  onSelectAnchor,
  selectedText = '',
  selectedMappingId = '',
  activePlaceholderKey = '',
  onSelectMapping,
  onPlaceholderClick,
  reviewHighlightTexts = [],
}) {
  const highlightTexts = useMemo(
    () => [
      ...mappings
        .filter((m) => m.approved !== false && m.action !== 'keep')
        .map((m) => m.original_text)
        .filter(Boolean),
      ...(reviewHighlightTexts || []).filter(Boolean),
    ],
    [mappings, reviewHighlightTexts],
  )

  const anchorFromNode = (node, text) => {
    const el = node?.nodeType === 1 ? node : node?.parentElement
    const host = el?.closest?.('[data-paragraph-index]')
    if (!host && !text) return null
    const index = host ? Number(host.getAttribute('data-paragraph-index')) : undefined
    const location = host?.getAttribute('data-location') || ''
    const tableIndex = host?.getAttribute('data-table-index')
    const row = host?.getAttribute('data-row')
    const col = host?.getAttribute('data-col')
    const blockId = location || host?.getAttribute('data-block-id') || ''
    return {
      selected_text: text || '',
      paragraph_index: Number.isNaN(index) ? undefined : index,
      block_id: blockId,
      ...(location ? { location } : {}),
      ...(tableIndex != null && row != null && col != null ? {
        table_index: Number(tableIndex),
        row: Number(row),
        col: Number(col),
      } : {}),
      source: 'document',
    }
  }

  const handleMouseUp = () => {
    const sel = window.getSelection()
    const text = (sel?.toString() || '').trim()
    if (text.length >= 2) onSelectText?.(text)
    const anchor = anchorFromNode(sel?.anchorNode, text)
    if (anchor && (text.length >= 2 || anchor.block_id)) onSelectAnchor?.(anchor)
  }

  const handlePlaceholderClick = (key) => {
    onPlaceholderClick?.(key)
    const mapping = mappings.find((m) => m.key === key)
    if (mapping) onSelectMapping?.(mapping.id)
  }

  if (!paragraphs.length) {
    return <div className="admin-empty">暂无正文，请先执行智能识别</div>
  }

  return (
    <div className="selectable-doc-preview" onMouseUp={handleMouseUp}>
      {paragraphs.map((p, i) => (
        <div
          key={p.index ?? i}
          data-paragraph-index={p.index}
          data-block-id={p.location || (p.is_heading ? `section:${p.index}` : `p:${p.index}`)}
          {...(p.location ? { 'data-location': p.location } : {})}
          {...(p.table_index != null ? {
            'data-table-index': p.table_index,
            'data-row': p.row,
            'data-col': p.col,
          } : {})}
          onClick={() => onSelectAnchor?.({
            selected_text: selectedText || p.text || '',
            paragraph_index: p.index,
            block_id: p.location || (p.is_heading ? `section:${p.index}` : `p:${p.index}`),
            ...(p.location ? { location: p.location } : {}),
            ...(p.table_index != null ? {
              table_index: p.table_index,
              row: p.row,
              col: p.col,
            } : {}),
            source: 'document',
          })}
        >
          {renderPreviewBlock(p, i, {
            highlightTexts,
            activePlaceholderKey,
            onPlaceholderClick: handlePlaceholderClick,
          })}
        </div>
      ))}
      {selectedText ? (
        <div className="selection-toolbar">
          已选中：「{selectedText.slice(0, 80)}{selectedText.length > 80 ? '…' : ''}」
        </div>
      ) : null}
    </div>
  )
}
