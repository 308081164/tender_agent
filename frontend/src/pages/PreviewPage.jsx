import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useApp } from '../App'
import PdfPreview from '../components/PdfPreview'
import { formatTime } from '../utils/format'

export default function PreviewPage() {
  const { id } = useParams()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const { showToast } = useApp()
  const [exports, setExports] = useState([])
  const [selectedId, setSelectedId] = useState(search.get('export') ? Number(search.get('export')) : null)
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const list = await api.listExports(id)
        if (cancelled) return
        setExports(list)
        const pick = selectedId || list[0]?.id || null
        setSelectedId(pick)
        if (pick) {
          const data = await api.previewExport(id, pick)
          if (!cancelled) setPreview(data)
        }
      } catch (e) {
        showToast(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [id])

  const switchExport = async (exportId) => {
    setSelectedId(exportId)
    setLoading(true)
    try {
      const data = await api.previewExport(id, exportId)
      setPreview(data)
      navigate(`/projects/${id}/preview?export=${exportId}`, { replace: true })
    } catch (e) {
      showToast(e.message)
    } finally {
      setLoading(false)
    }
  }

  const download = async () => {
    if (!selectedId) return
    try {
      const blob = await api.downloadExport(id, selectedId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = preview?.filename || '标书.docx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      showToast(e.message)
    }
  }

  const pdfSrc = preview?.preview_url
    || (selectedId ? api.previewPdfUrl(id, selectedId) : null)

  return (
    <div className="panel">
      <div className="home-head">
        <div>
          <div className="wizard-kicker">导出预览</div>
          <h2>{preview?.title || '标书预览'}</h2>
          <p className="lead">
            {preview?.filename
              ? `${preview.filename} · ${formatTime(preview.created_at)} · PDF 高保真分页预览`
              : '按 Word 分页与样式预览已导出文档'}
          </p>
        </div>
        <div className="actions" style={{ marginTop: 0 }}>
          <Link className="btn secondary" to={`/projects/${id}/step/6`}>返回向导</Link>
          <button className="secondary" onClick={download} disabled={!selectedId}>下载</button>
          <button className="ghost" onClick={() => navigate('/')}>首页</button>
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

      {loading && <div className="empty">正在生成 PDF 预览（首次可能需数十秒）…</div>}
      {!loading && !preview && <div className="empty">暂无导出记录，请先导出 Word。</div>}
      {!loading && preview && pdfSrc && (
        <PdfPreview src={pdfSrc} title={preview.title || '标书预览'} />
      )}
    </div>
  )
}
