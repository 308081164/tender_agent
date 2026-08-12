import React from 'react'

const PLACEHOLDER_RE = /\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g
const AI_MARKER_RE = /【AI_GENERATED:([^】]+)】/g

function renderHighlightedSegments(text, highlightTexts = []) {
  if (!text) return text
  const highlights = (highlightTexts || [])
    .filter(Boolean)
    .sort((a, b) => b.length - a.length)

  if (!highlights.length) {
    return renderTokenizedText(text)
  }

  const parts = []
  let cursor = 0
  while (cursor < text.length) {
    let nearest = null
    for (const h of highlights) {
      const idx = text.indexOf(h, cursor)
      if (idx !== -1 && (nearest === null || idx < nearest.index)) {
        nearest = { index: idx, text: h }
      }
    }
    if (!nearest) {
      parts.push(...flattenTokenParts(text.slice(cursor)))
      break
    }
    if (nearest.index > cursor) {
      parts.push(...flattenTokenParts(text.slice(cursor, nearest.index)))
    }
    parts.push(
      <mark key={`hl-${nearest.index}`} className="detected-token" title="待替换原文">
        {nearest.text}
      </mark>,
    )
    cursor = nearest.index + nearest.text.length
  }
  return parts.length ? parts : text
}

function flattenTokenParts(segment) {
  if (!segment) return []
  const parts = []
  let last = 0
  let match
  const re = new RegExp(`${PLACEHOLDER_RE.source}|${AI_MARKER_RE.source}`, 'g')
  while ((match = re.exec(segment)) !== null) {
    if (match.index > last) parts.push(segment.slice(last, match.index))
    if (match[0].startsWith('{{')) {
      parts.push(
        <mark key={`ph-${match.index}`} className="placeholder-token" title={`占位符：${match[1]}`}>
          {match[0]}
        </mark>,
      )
    } else {
      parts.push(
        <mark key={`ai-${match.index}`} className="ai-marker-token" title={`AI 章节：${match[1]}`}>
          {match[0]}
        </mark>,
      )
    }
    last = match.index + match[0].length
  }
  if (last < segment.length) parts.push(segment.slice(last))
  return parts
}

function renderTokenizedText(text) {
  const parts = []
  let last = 0
  let match
  const re = new RegExp(`${PLACEHOLDER_RE.source}|${AI_MARKER_RE.source}`, 'g')
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index))
    if (match[0].startsWith('{{')) {
      parts.push(
        <mark key={`ph-${match.index}`} className="placeholder-token" title={`占位符：${match[1]}`}>
          {match[0]}
        </mark>,
      )
    } else {
      parts.push(
        <mark key={`ai-${match.index}`} className="ai-marker-token" title={`AI 章节：${match[1]}`}>
          {match[0]}
        </mark>,
      )
    }
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts.length ? parts : text
}

export function renderPlaceholderText(text, highlightTexts) {
  if (highlightTexts?.length) return renderHighlightedSegments(text, highlightTexts)
  return renderTokenizedText(text)
}

export default function DocxTextPreview({
  paragraphs = [],
  truncated = false,
  highlightTexts = [],
}) {
  if (!paragraphs.length) {
    return <div className="admin-empty">未能提取正文内容</div>
  }
  return (
    <div className="preview-doc preview-text admin-template-text">
      {paragraphs.map((p, i) => (
        p.is_heading ? (
          <div key={i} className={`preview-h level-${Math.min(p.level || 1, 3)}`}>
            {renderPlaceholderText(p.text, highlightTexts)}
          </div>
        ) : (
          <p key={i} className="preview-p">{renderPlaceholderText(p.text, highlightTexts)}</p>
        )
      ))}
      {truncated ? <p className="muted preview-truncated">内容较长，此处仅展示前 800 段；完整版请下载 DOCX。</p> : null}
    </div>
  )
}
