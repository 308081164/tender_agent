import React, { useMemo, useState } from 'react'
import { api } from '../../api/client'

export default function WorkspaceReviewPanel({
  projectId,
  onReviewComplete,
  onHighlightTexts,
  showToast,
}) {
  const [busy, setBusy] = useState(false)
  const [review, setReview] = useState(null)

  const highlightTexts = useMemo(() => {
    if (!review) return []
    const texts = []
    ;[...(review.issues || []), ...(review.warnings || [])].forEach((item) => {
      const msg = item.message || ''
      const m = msg.match(/[「『"](.+?)[」』"]/)
      if (m?.[1]) texts.push(m[1])
      if (item.field && item.field.length > 1) texts.push(String(item.field))
      if (item.excerpt) texts.push(String(item.excerpt))
    })
    return [...new Set(texts.filter((t) => t && t.length >= 2))].slice(0, 12)
  }, [review])

  React.useEffect(() => {
    onHighlightTexts?.(highlightTexts)
  }, [highlightTexts, onHighlightTexts])

  const run = async () => {
    setBusy(true)
    try {
      const result = await api.docReview(projectId)
      setReview(result)
      await api.saveProgress(projectId, { current_step: 4, advance: false })
      onReviewComplete?.(result)
      showToast?.(result.can_export ? '审阅完成，可进入导出' : '审阅发现问题，请按提示修改')
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="workspace-review-panel card-block">
      <h4>AI 文档审查</h4>
      <p className="muted tiny">检查矛盾、遗漏与残留占位符；问题片段将在左侧预览中高亮。</p>
      <button type="button" onClick={run} disabled={busy}>
        {busy ? '审查中…' : '开始 AI 审查'}
      </button>
      {review ? (
        <div className="review-results" style={{ marginTop: 12 }}>
          <p>
            状态 <span className={`level-${review.status}`}>{review.status}</span>
            {review.can_export ? ' · 可导出' : ' · 请先处理问题'}
          </p>
          {(review.issues || []).map((item, i) => (
            <div key={`i-${i}`} className="level-red" style={{ fontSize: 13 }}>{item.message}</div>
          ))}
          {(review.warnings || []).map((item, i) => (
            <div key={`w-${i}`} className="level-yellow" style={{ fontSize: 13 }}>{item.message}</div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
