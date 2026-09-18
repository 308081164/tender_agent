import React from 'react'

export default function ProcessingOverlay({
  open,
  title = '正在处理…',
  message = '请勿关闭或离开当前页面，以免任务中断。',
  blocking = true,
}) {
  if (!open) return null
  return (
    <div className={`processing-overlay ${blocking ? 'blocking' : ''}`} role="alert" aria-live="assertive">
      <div className="processing-overlay-card">
        <div className="processing-spinner" aria-hidden="true" />
        <h3>{title}</h3>
        <p className="muted">{message}</p>
      </div>
    </div>
  )
}
