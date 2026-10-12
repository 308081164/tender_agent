import React, { useEffect, useState } from 'react'
import { api } from '../api/client'

export default function LogViewerModal({ open, onClose, showToast }) {
  const [loading, setLoading] = useState(false)
  const [payload, setPayload] = useState(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setPayload(null)
      try {
        const data = await api.recentLogs()
        if (!cancelled) setPayload(data)
      } catch (e) {
        showToast?.(e.message)
        if (!cancelled) onClose?.()
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [open, onClose, showToast])

  if (!open) return null

  const lines = payload?.lines || []

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal-panel log-viewer-modal"
        role="dialog"
        aria-labelledby="log-viewer-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <p className="muted" style={{ margin: 0, fontSize: 13 }}>运行诊断</p>
            <h2 id="log-viewer-title">最近日志</h2>
            {payload?.data_dir ? (
              <p className="muted" style={{ margin: '4px 0 0', fontSize: 12 }}>
                目录：<code>{payload.data_dir}</code>
              </p>
            ) : null}
          </div>
          <button type="button" className="ghost" onClick={onClose}>关闭</button>
        </div>
        <div className="log-viewer-body preview-body">
          {loading ? (
            <p className="muted">加载中…</p>
          ) : lines.length === 0 ? (
            <p className="muted">暂无日志文件或文件为空。</p>
          ) : (
            <pre className="log-viewer-pre">{lines.join('\n')}</pre>
          )}
        </div>
      </div>
    </div>
  )
}
