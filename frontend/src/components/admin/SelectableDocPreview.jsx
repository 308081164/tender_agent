import React, { useMemo } from 'react'
import { renderPlaceholderText } from './DocxTextPreview'
import { paragraphPreviewStyle } from './FormatInfoSummary'

export default function SelectableDocPreview({
  paragraphs = [],
  mappings = [],
  onSelectText,
  selectedText = '',
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

  if (!paragraphs.length) {
    return <div className="admin-empty">暂无正文，请先执行智能识别</div>
  }

  return (
    <div className="selectable-doc-preview" onMouseUp={handleMouseUp}>
      {paragraphs.map((p, i) => {
        const text = p.display_text ?? p.text
        const changed = p.changed || (p.display_text && p.display_text !== p.text)
        const style = paragraphPreviewStyle(p)
        const content = renderPlaceholderText(text, highlightTexts)
        return p.is_heading ? (
          <div
            key={i}
            className={`preview-h level-${Math.min(p.level || 1, 3)} ${changed ? 'mapping-changed' : ''}`}
            style={style}
            title={p.style || undefined}
          >
            {content}
          </div>
        ) : (
          <p key={i} className={`preview-p ${changed ? 'mapping-changed' : ''}`} style={style} title={p.style || undefined}>
            {content}
          </p>
        )
      })}
      {selectedText ? (
        <div className="selection-toolbar">
          已选中：「{selectedText.slice(0, 80)}{selectedText.length > 80 ? '…' : ''}」
        </div>
      ) : null}
    </div>
  )
}
