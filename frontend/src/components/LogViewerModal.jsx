import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import {
  LOG_RANGE_PRESETS,
  customRange,
  filterLogLines,
  presetRange,
} from './logTimeFilter'

function resolveLogRange(preset, anchorNow, appliedStart, appliedEnd) {
  if (preset === 'all') return { range: null, mode: 'all' }
  if (preset === 'custom') {
    const result = customRange(appliedStart, appliedEnd)
    if (!result.ok && result.reason === 'incomplete') {
      return { range: null, mode: 'pending', hint: '请选择开始和结束时间，然后点击应用。' }
    }
    if (!result.ok && result.reason === 'order') {
      return { range: null, mode: 'error', error: '开始时间不能晚于结束时间' }
    }
    if (!result.ok) return { range: null, mode: 'error', error: '时间格式无效' }
    return { range: result.range, mode: 'custom' }
  }
  return { range: presetRange(preset, new Date(anchorNow)), mode: 'preset' }
}

export default function LogViewerModal({ open, onClose, showToast }) {
  const [loading, setLoading] = useState(false)
  const [payload, setPayload] = useState(null)
  const [preset, setPreset] = useState('all')
  const [anchorNow, setAnchorNow] = useState(() => Date.now())
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [appliedStart, setAppliedStart] = useState('')
  const [appliedEnd, setAppliedEnd] = useState('')

  useEffect(() => {
    if (!open) return
    setPreset('all')
    setAnchorNow(Date.now())
    setCustomStart('')
    setCustomEnd('')
    setAppliedStart('')
    setAppliedEnd('')
  }, [open])

  useEffect(() => {
    if (!open) return undefined
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

  const lines = payload?.lines || []
  const selection = useMemo(
    () => resolveLogRange(preset, anchorNow, appliedStart, appliedEnd),
    [preset, anchorNow, appliedStart, appliedEnd],
  )
  const visible = useMemo(
    () => (selection.mode === 'error' ? [] : filterLogLines(lines, selection.range)),
    [lines, selection],
  )
  const filtering = selection.mode === 'preset' || selection.mode === 'custom'

  const applyCustom = () => {
    setAppliedStart(customStart)
    setAppliedEnd(customEnd)
  }

  if (!open) return null

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
        <div className="log-viewer-filter" role="group" aria-label="日志周期">
          <div className="log-viewer-filter-row">
            <span className="log-viewer-filter-label">日志周期</span>
            <div className="filter-tabs">
              {LOG_RANGE_PRESETS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={preset === item.id ? 'filter-tab active' : 'filter-tab'}
                  aria-pressed={preset === item.id}
                  onClick={() => {
                    setPreset(item.id)
                    setAnchorNow(Date.now())
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          {preset === 'custom' ? (
            <div className="log-viewer-custom">
              <label>
                开始
                <input
                  type="text"
                  inputMode="numeric"
                  placeholder="2026-10-14 16:47"
                  spellCheck={false}
                  value={customStart}
                  onChange={(e) => setCustomStart(e.target.value)}
                />
              </label>
              <label>
                结束
                <input
                  type="text"
                  inputMode="numeric"
                  placeholder="2026-10-14 16:47"
                  spellCheck={false}
                  value={customEnd}
                  onChange={(e) => setCustomEnd(e.target.value)}
                />
              </label>
              <button type="button" className="secondary tiny" onClick={applyCustom}>
                应用
              </button>
              <p className="log-viewer-filter-meta">时间格式：2026-10-14 16:47，结束这一分钟里的日志也会包含。</p>
            </div>
          ) : null}
          {selection.hint ? <p className="log-viewer-filter-meta">{selection.hint}</p> : null}
          {filtering ? (
            <p className="log-viewer-filter-meta" aria-live="polite">
              显示 {visible.length} / {lines.length} 行
            </p>
          ) : null}
        </div>
        <div className="log-viewer-body preview-body">
          {loading ? (
            <p className="muted">加载中…</p>
          ) : lines.length === 0 ? (
            <p className="muted">暂无日志文件或文件为空。</p>
          ) : selection.mode === 'error' ? (
            <div className="log-viewer-empty" role="status">
              <strong>{selection.error}</strong>
              <p className="muted">请调整开始或结束时间后再查看。</p>
            </div>
          ) : visible.length === 0 ? (
            <div className="log-viewer-empty" role="status">
              <strong>所选时间范围内没有日志</strong>
              <p className="muted">这段时间内没有带时间戳的记录。可以换一个周期，或改回「全部」。</p>
            </div>
          ) : (
            <pre className="log-viewer-pre">{visible.join('\n')}</pre>
          )}
        </div>
      </div>
    </div>
  )
}
