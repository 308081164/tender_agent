import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import PdfPreview from '../PdfPreview'
import OnlyOfficeEditor from '../chat/OnlyOfficeEditor'
import ProjectFieldEditorPane from './ProjectFieldEditorPane'

async function readFetchError(res) {
  const text = await res.text()
  if (!text) return `预览失败（HTTP ${res.status}）`
  try {
    const data = JSON.parse(text)
    if (typeof data.detail === 'string') return data.detail
    return text
  } catch {
    return text.slice(0, 400)
  }
}

export default function ProjectDocumentPane({
  projectId,
  sessionId,
  workspace,
  context,
  onlyOfficeEnabled,
  refreshToken,
  onPreviewError,
  onFieldsSaved,
  onAgentFollowup,
  showToast,
}) {
  const [pdfFailed, setPdfFailed] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [previewStatus, setPreviewStatus] = useState(null)
  const [mode, setMode] = useState('pdf')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [pdfOk, setPdfOk] = useState(false)
  const debounceRef = useRef(null)
  const pollRef = useRef(null)

  const pdfSrc = projectId && pdfOk
    ? `/api/projects/${projectId}/draft-preview.pdf?t=${encodeURIComponent(refreshToken || '')}`
    : null

  const loadStatus = useCallback(async () => {
    if (!projectId) return
    try {
      const st = await api.getDraftPreviewStatus(projectId)
      setPreviewStatus(st)
    } catch {
      setPreviewStatus(null)
    }
  }, [projectId])

  const pollAsyncJob = useCallback((jobId) => {
    if (pollRef.current) clearInterval(pollRef.current)
    let tries = 0
    pollRef.current = setInterval(async () => {
      tries += 1
      if (tries > 40) {
        clearInterval(pollRef.current)
        return
      }
      try {
        const job = await api.getDraftPreviewJob(projectId, jobId)
        if (job.status === 'done' && job.pdf_ready) {
          clearInterval(pollRef.current)
          setPdfFailed(false)
          setPdfOk(true)
          setPreviewError('')
        } else if (job.status === 'failed') {
          clearInterval(pollRef.current)
          setPreviewError(job.error || '异步预览失败')
        }
      } catch {
        clearInterval(pollRef.current)
      }
    }, 2000)
  }, [projectId])

  const runPreviewFetch = useCallback(async (force = false) => {
    if (!projectId) return
    setPreviewLoading(true)
    setPreviewError('')
    try {
      const q = force ? 'force=true&' : ''
      const url = `/api/projects/${projectId}/draft-preview.pdf?${q}t=${encodeURIComponent(Date.now())}`
      const res = await fetch(url, { method: 'GET' })
      if (!res.ok) {
        const msg = await readFetchError(res)
        throw new Error(msg)
      }
      setPdfFailed(false)
      setPdfOk(true)
    } catch (e) {
      setPdfOk(false)
      setPdfFailed(true)
      const msg = e.message || '预览失败'
      setPreviewError(msg)
      onPreviewError?.(msg)
      if (msg.includes('转换') || msg.includes('引擎') || msg.includes('Aspose')) {
        setMode((m) => (m === 'pdf' ? 'edit' : m))
      }
      try {
        const job = await api.startDraftPreviewAsync(projectId)
        if (job?.job_id) pollAsyncJob(job.job_id)
      } catch {
        /* async optional */
      }
    } finally {
      setPreviewLoading(false)
      loadStatus()
    }
  }, [projectId, onPreviewError, loadStatus, pollAsyncJob])

  useEffect(() => {
    setPdfFailed(false)
    setPdfOk(false)
    if (onlyOfficeEnabled && sessionId) setMode('onlyoffice')
    else setMode('pdf')
    loadStatus()
  }, [projectId, sessionId, onlyOfficeEnabled, loadStatus])

  useEffect(() => {
    if (!projectId) return undefined
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => runPreviewFetch(false), 400)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [projectId, refreshToken, runPreviewFetch])

  const tabs = (
    <div className="doc-workspace-tabs">
      <button type="button" className={mode === 'pdf' ? 'active' : ''} onClick={() => setMode('pdf')}>
        PDF 预览
      </button>
      {onlyOfficeEnabled && sessionId ? (
        <button type="button" className={mode === 'onlyoffice' ? 'active' : ''} onClick={() => setMode('onlyoffice')}>
          Word 编辑
        </button>
      ) : (
        <button type="button" className={mode === 'edit' ? 'active' : ''} onClick={() => setMode('edit')}>
          可编辑
        </button>
      )}
    </div>
  )

  return (
    <div className="doc-workspace project-doc-pane">
      <div className="doc-workspace-toolbar">
        <div>
          <strong>标书草稿预览</strong>
          {previewLoading ? <span className="muted"> 更新中…</span> : null}
          {previewStatus?.pdf_engine ? (
            <span className="muted tiny"> · 引擎 {previewStatus.pdf_engine}</span>
          ) : null}
        </div>
        {tabs}
      </div>
      <div className="doc-workspace-body">
        {mode === 'onlyoffice' && sessionId ? (
          <OnlyOfficeEditor sessionId={sessionId} workspace={workspace} onSaved={() => runPreviewFetch(true)} />
        ) : mode === 'edit' ? (
          <ProjectFieldEditorPane
            projectId={projectId}
            context={context}
            showToast={showToast}
            onSaved={async () => {
              await onFieldsSaved?.()
              await runPreviewFetch(true)
            }}
            onFollowup={onAgentFollowup}
          />
        ) : pdfSrc && !pdfFailed ? (
          <PdfPreview
            src={pdfSrc}
            title="草稿预览"
            className="doc-workspace-pdf"
            onLoadError={() => {
              setPdfFailed(true)
              onPreviewError?.('PDF 在浏览器中加载失败')
            }}
          />
        ) : (
          <div className="doc-workspace-empty">
            <p>{previewError || previewStatus?.hint || '预览暂不可用。'}</p>
            {!previewStatus?.pdf_engine ? (
              <p className="muted">可能缺少 PDF 转换引擎（Aspose 授权或 LibreOffice）。可切换到「可编辑」继续填字段。</p>
            ) : (
              <button type="button" className="ghost" onClick={() => runPreviewFetch(true)} disabled={previewLoading}>
                重试预览
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
