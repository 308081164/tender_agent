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
  selectedText = '',
  selectedMappingId = '',
  activePlaceholderKey = '',
  onSelectMapping,
  onPlaceholderClick,
}) {
  const highlightTexts = useMemo(
    () => mappings
      .filter((m) => m.approved !== false && m.action !== 'keep')
      .map((m) => m.original_text)
      .filter(Boolean),
    [mappings],
  )

  const handleMouseUp = () => {
    const sel = window.getSelection()
    const text = (sel?.toString() || '').trim()
    if (text.length >= 2) onSelectText?.(text)
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
      {paragraphs.map((p, i) => renderPreviewBlock(p, i, {
        highlightTexts,
        activePlaceholderKey,
        onPlaceholderClick: handlePlaceholderClick,
      }))}
      {selectedText ? (
        <div className="selection-toolbar">
          已选中：「{selectedText.slice(0, 80)}{selectedText.length > 80 ? '…' : ''}」
        </div>
      ) : null}
    </div>
  )
}
