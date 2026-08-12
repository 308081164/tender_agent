import React, { useEffect, useState } from 'react'
import { api } from '../../api/client'
import PdfPreview from '../PdfPreview'
import DocxTextPreview from './DocxTextPreview'

export default function TemplatePreviewPanel({ templateId, compact = false, highlightTexts = [] }) {
  const [preview, setPreview] = useState(null)
  const [mode, setMode] = useState('pdf')
  const [loading, setLoading] = useState(true)
  const [pdfFailed, setPdfFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setPdfFailed(false)
    setMode('pdf')
    api.adminTemplatePreview(templateId)
      .then((data) => {
        if (cancelled) return
        setPreview(data)
        if (!data.pdf_available) {
          setMode('text')
        }
      })
      .catch(() => {
        if (!cancelled) setPreview(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [templateId])

  if (loading) {
    return <div className="admin-loading">{compact ? '加载预览…' : '正在加载模板内容…'}</div>
  }
  if (!preview) {
    return <div className="admin-empty">无法加载模板预览</div>
  }

  const pdfSrc = mode === 'pdf' && preview.pdf_available && !pdfFailed
    ? api.adminTemplatePreviewPdfUrl(templateId)
    : null

  return (
    <div className={`admin-template-preview ${compact ? 'compact' : ''}`}>
      <div className="admin-preview-tabs">
        <button
          type="button"
          className={`filter-tab ${mode === 'pdf' ? 'active' : ''}`}
          disabled={!preview.pdf_available || pdfFailed}
          onClick={() => setMode('pdf')}
        >
          PDF 分页预览
        </button>
        <button
          type="button"
          className={`filter-tab ${mode === 'text' ? 'active' : ''}`}
          onClick={() => setMode('text')}
        >
          正文结构
        </button>
        {!preview.pdf_available || pdfFailed ? (
          <span className="muted admin-preview-hint">
            {pdfFailed && preview.pdf_available
              ? 'PDF 转换失败，已切换正文预览'
              : 'PDF 预览不可用，已使用正文结构'}
          </span>
        ) : preview.pdf_engine === 'aspose' ? (
          <span className="muted admin-preview-hint">内置 Aspose 引擎</span>
        ) : preview.pdf_engine === 'libreoffice' ? (
          <span className="muted admin-preview-hint">LibreOffice 引擎</span>
        ) : null}
      </div>
      {mode === 'pdf' && pdfSrc ? (
        <PdfPreview
          src={pdfSrc}
          title={preview.name || '模板预览'}
          onLoadError={() => {
            setPdfFailed(true)
            setMode('text')
          }}
        />
      ) : (
        <DocxTextPreview
          paragraphs={preview.paragraphs}
          truncated={preview.truncated}
          highlightTexts={highlightTexts}
        />
      )}
      {preview.placeholder_count > 0 ? (
        <div className="admin-preview-meta muted">
          含 {preview.placeholder_count} 个占位符
          {preview.placeholders?.length
            ? `：${preview.placeholders.slice(0, 8).map((p) => `{{${p}}}`).join('、')}${preview.placeholder_count > 8 ? '…' : ''}`
            : ''}
        </div>
      ) : null}
    </div>
  )
}
