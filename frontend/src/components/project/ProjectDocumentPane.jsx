import React, { useEffect, useRef, useState } from 'react'
import PdfPreview from '../PdfPreview'
import OnlyOfficeEditor from '../chat/OnlyOfficeEditor'

export default function ProjectDocumentPane({
  projectId,
  sessionId,
  workspace,
  onlyOfficeEnabled,
  refreshToken,
  onPreviewError,
}) {
  const [pdfFailed, setPdfFailed] = useState(false)
  const [mode, setMode] = useState('pdf')
  const [previewLoading, setPreviewLoading] = useState(false)
  const debounceRef = useRef(null)

  const pdfSrc = projectId
    ? `/api/projects/${projectId}/draft-preview.pdf?t=${encodeURIComponent(refreshToken || '')}`
    : null

  useEffect(() => {
    setPdfFailed(false)
    if (onlyOfficeEnabled && sessionId) setMode('onlyoffice')
    else setMode('pdf')
  }, [projectId, sessionId, onlyOfficeEnabled])

  useEffect(() => {
    if (!projectId) return undefined
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPreviewLoading(true)
      fetch(pdfSrc, { method: 'GET' })
        .then((r) => {
          if (!r.ok) throw new Error('预览失败')
          setPdfFailed(false)
        })
        .catch((e) => {
          setPdfFailed(true)
          onPreviewError?.(e.message)
        })
        .finally(() => setPreviewLoading(false))
    }, 2500)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [projectId, refreshToken, pdfSrc, onPreviewError])

  return (
    <div className="doc-workspace project-doc-pane">
      <div className="doc-workspace-toolbar">
        <div>
          <strong>标书草稿预览</strong>
          {previewLoading ? <span className="muted"> 更新中…</span> : null}
        </div>
        <div className="doc-workspace-tabs">
          {onlyOfficeEnabled && sessionId ? (
            <button type="button" className={mode === 'onlyoffice' ? 'active' : ''} onClick={() => setMode('onlyoffice')}>
              Word 编辑
            </button>
          ) : null}
          <button type="button" className={mode === 'pdf' ? 'active' : ''} onClick={() => setMode('pdf')}>PDF 预览</button>
          {!onlyOfficeEnabled ? (
            <span className="muted tiny">未部署 OnlyOffice 时仅支持 PDF 与字段驱动预览</span>
          ) : null}
        </div>
      </div>
      <div className="doc-workspace-body">
        {mode === 'onlyoffice' && sessionId ? (
          <OnlyOfficeEditor sessionId={sessionId} workspace={workspace} onSaved={() => {}} />
        ) : pdfSrc && !pdfFailed ? (
          <PdfPreview
            src={pdfSrc}
            title="草稿预览"
            className="doc-workspace-pdf"
            onLoadError={() => { setPdfFailed(true); onPreviewError?.('PDF 预览不可用') }}
          />
        ) : (
          <div className="doc-workspace-empty">
            <p>预览暂不可用（可能缺少 PDF 转换引擎）。字段保存后会自动重试。</p>
          </div>
        )}
      </div>
    </div>
  )
}
