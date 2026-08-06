import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import PdfPreview from './PdfPreview'
import { formatTime } from '../utils/format'

export default function PreviewModal({ projectId, exportId = null, onClose, showToast }) {
  const [exports, setExports] = useState([])
  const [selectedId, setSelectedId] = useState(exportId)
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const list = await api.listExports(projectId)
        if (cancelled) return
        setExports(list)
        const pick = exportId || list[0]?.id || null
        setSelectedId(pick)
        if (pick) {
          const data = await api.previewExport(projectId, pick)
          if (!cancelled) setPreview(data)
        } else {
          setPreview(null)
        }
      } catch (e) {
        showToast?.(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [projectId, exportId, showToast])

  const switchExport = async (id) => {
    setSelectedId(id)
    setLoading(true)
    try {
      const data = await api.previewExport(projectId, id)
      setPreview(data)
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setLoading(false)
    }
  }

  const download = async () => {
    if (!selectedId) return
    try {
      const blob = await api.downloadExport(projectId, selectedId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = preview?.filename || '标书.docx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      showToast?.(e.message)
    }
  }

  const pdfSrc = preview?.preview_url
    || (selectedId ? api.previewPdfUrl(projectId, selectedId) : null)

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel preview-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="wizard-kicker">标书预览</div>
            <h2>{preview?.title || '导出预览'}</h2>
            {preview?.created_at && (
              <p className="lead" style={{ marginBottom: 0 }}>
                {preview.filename} · {formatTime(preview.created_at)} · PDF 高保真分页预览
              </p>
            )}
          </div>
          <div className="actions" style={{ marginTop: 0 }}>
            <Link className="btn secondary" to={`/projects/${projectId}/preview`}>独立页面</Link>
            <button className="secondary" onClick={download} disabled={!selectedId}>下载</button>
            <button className="ghost" onClick={onClose}>关闭</button>
          </div>
        </div>

        {exports.length > 1 && (
          <div className="filter-tabs" style={{ marginBottom: 16 }}>
            {exports.map((e) => (
              <button
                key={e.id}
                className={`filter-tab ${selectedId === e.id ? 'active' : ''}`}
                onClick={() => switchExport(e.id)}
              >
                #{e.id} · {formatTime(e.created_at)}
              </button>
            ))}
          </div>
        )}

        <div className="preview-body">
          {loading && <div className="empty">正在生成 PDF 预览（首次可能需数十秒）…</div>}
          {!loading && !preview && <div className="empty">暂无导出记录，请先导出 Word。</div>}
          {!loading && preview && pdfSrc && (
            <PdfPreview src={pdfSrc} title={preview.title || '导出预览'} />
          )}
        </div>
      </div>
    </div>
  )
}
