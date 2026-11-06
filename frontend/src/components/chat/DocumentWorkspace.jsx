import React, { useEffect, useRef, useState } from 'react'
import PdfPreview from '../PdfPreview'
import SelectableDocPreview from '../admin/SelectableDocPreview'
import OnlyOfficeEditor from './OnlyOfficeEditor'
import HtmlDocPreview, { scrollHtmlPreviewToParagraph } from './HtmlDocPreview'

export default function DocumentWorkspace({
  sessionId,
  workspace,
  paragraphs,
  selectedText,
  onSelectText,
  onSelectAnchor,
  onParagraphEdit,
  onRefresh,
  onlyOfficeReady = false,
  toolbarLeading = null,
  highlightTexts = [],
}) {
  const [mode, setMode] = useState('pdf')
  const [editingIndex, setEditingIndex] = useState(null)
  const [editText, setEditText] = useState('')
  const [pdfFailed, setPdfFailed] = useState(false)
  const [onlyOfficeFailed, setOnlyOfficeFailed] = useState(false)
  const [structureHtmlFailed, setStructureHtmlFailed] = useState(false)
  const [structurePdfFailed, setStructurePdfFailed] = useState(false)
  const structuredPreviewRef = useRef(null)
  const htmlIframeRef = useRef(null)

  const hasDoc = !!(workspace?.draft_object_key || workspace?.template_object_key)
  const hasParagraphs = (paragraphs || []).some((p) => (p.text || '').trim().length > 0 || p.is_table)
  const pdfSrc = hasDoc && sessionId ? `/api/chat/sessions/${sessionId}/workspace/preview.pdf` : null
  const htmlSrc = hasDoc && sessionId ? `/api/chat/sessions/${sessionId}/workspace/preview.html` : null

  useEffect(() => {
    setPdfFailed(false)
    setOnlyOfficeFailed(false)
    setStructureHtmlFailed(false)
    setStructurePdfFailed(false)
    if (hasDoc && onlyOfficeReady) {
      setMode('onlyoffice')
    } else {
      setMode(hasDoc ? 'pdf' : 'structure')
    }
  }, [sessionId, hasDoc, onlyOfficeReady])

  const fallbackToReadable = () => {
    setOnlyOfficeFailed(true)
    if (!pdfFailed && hasDoc) setMode('pdf')
    else setMode('structure')
  }

  const startEdit = (p) => {
    setEditingIndex(p.index)
    setEditText(p.text || '')
  }

  const saveEdit = async () => {
    if (editingIndex == null) return
    await onParagraphEdit?.(editingIndex, editText)
    setEditingIndex(null)
    onRefresh?.()
  }

  const scrollPreviewToParagraph = (index) => {
    if (index == null) return
    if (!structureHtmlFailed && htmlSrc) {
      scrollHtmlPreviewToParagraph(htmlIframeRef, index)
      return
    }
    if (!structurePdfFailed && pdfSrc && structureHtmlFailed) {
      return
    }
    const host = structuredPreviewRef.current
    const el = host?.querySelector?.(`[data-paragraph-index="${index}"]`)
    el?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  }

  const structureUsesHtml = hasDoc && htmlSrc && !structureHtmlFailed
  const structureUsesPdf = hasDoc && pdfSrc && structureHtmlFailed && !structurePdfFailed
  const structureUsesStructured = !structureUsesHtml && !structureUsesPdf

  return (
    <div className="doc-workspace">
      <div className="doc-workspace-toolbar">
        <div className="doc-workspace-toolbar-title">
          {toolbarLeading}
          <strong>{workspace?.filename || '文档工作区'}</strong>
          {workspace?.version ? <span className="muted"> v{workspace.version}</span> : null}
        </div>
        <div className="doc-workspace-tabs">
          {onlyOfficeReady && hasDoc ? (
            <button type="button" className={mode === 'onlyoffice' ? 'active' : ''} onClick={() => { setOnlyOfficeFailed(false); setMode('onlyoffice') }}>Word 编辑</button>
          ) : null}
          <button type="button" className={mode === 'pdf' ? 'active' : ''} onClick={() => setMode('pdf')} disabled={!hasDoc}>PDF 预览</button>
          <button type="button" className={mode === 'structure' ? 'active' : ''} onClick={() => setMode('structure')}>段落编辑</button>
          {hasDoc ? (
            <a className="ghost linkish" href={`/api/chat/sessions/${sessionId}/workspace/download`} download>下载 DOCX</a>
          ) : null}
        </div>
      </div>

      <div className="doc-workspace-body">
        {!hasDoc ? (
          <div className="doc-workspace-empty">
            <p>请通过右侧聊天框上传模板 DOCX，或点击 📎 按钮。</p>
            <p className="muted">上传后可按编写要求生成标书，并支持选中片段多轮修改。</p>
            {onlyOfficeReady ? <p className="muted">OnlyOffice 已就绪，上传后将自动进入 Word 在线编辑模式。</p> : null}
          </div>
        ) : mode === 'onlyoffice' && onlyOfficeReady && !onlyOfficeFailed ? (
          <OnlyOfficeEditor
            sessionId={sessionId}
            workspace={workspace}
            onSaved={onRefresh}
            onAnchor={onSelectAnchor}
            highlightTexts={highlightTexts}
            onUnavailable={fallbackToReadable}
          />
        ) : mode === 'pdf' && pdfSrc && !pdfFailed ? (
          <PdfPreview
            src={pdfSrc}
            title={workspace?.filename || '文档'}
            className="doc-workspace-pdf"
            onLoadError={() => { setPdfFailed(true); setMode('structure') }}
          />
        ) : (
          <div className="doc-structure-pane">
            <div className="doc-structure-primary">
              {!hasParagraphs && hasDoc && structureUsesStructured ? (
                <div className="doc-workspace-empty">
                  <p className="muted">PDF/OnlyOffice 暂不可用，且未能解析段落。请尝试「下载 DOCX」本地打开，或稍后重试预览。</p>
                </div>
              ) : null}
              {structureUsesHtml ? (
                <HtmlDocPreview
                  src={htmlSrc}
                  title={workspace?.filename || '文档'}
                  className="doc-workspace-html"
                  iframeRef={htmlIframeRef}
                  onSelectText={onSelectText}
                  onSelectAnchor={onSelectAnchor}
                  onLoadError={() => setStructureHtmlFailed(true)}
                />
              ) : null}
              {structureUsesPdf ? (
                <PdfPreview
                  src={pdfSrc}
                  title={workspace?.filename || '文档'}
                  className="doc-workspace-pdf doc-structure-pdf-fallback"
                  onLoadError={() => setStructurePdfFailed(true)}
                />
              ) : null}
              {structureUsesStructured ? (
                <div
                  ref={structuredPreviewRef}
                  className="preview-doc preview-text doc-word-page doc-structure-preview"
                >
                  <SelectableDocPreview
                    paragraphs={paragraphs}
                    mappings={[]}
                    selectedText={selectedText}
                    onSelectText={onSelectText}
                    onSelectAnchor={onSelectAnchor}
                    reviewHighlightTexts={highlightTexts}
                  />
                </div>
              ) : null}
            </div>
            <div className="paragraph-edit-list">
              <h4>段落快速编辑</h4>
              {(paragraphs || []).slice(0, 40).map((p) => (
                <div
                  key={p.index}
                  className="paragraph-edit-row"
                  role="button"
                  tabIndex={0}
                  onClick={() => scrollPreviewToParagraph(p.index)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      scrollPreviewToParagraph(p.index)
                    }
                  }}
                >
                  {editingIndex === p.index ? (
                    <>
                      <textarea
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        rows={3}
                        onClick={(e) => e.stopPropagation()}
                      />
                      <div className="row-actions">
                        <button type="button" onClick={(e) => { e.stopPropagation(); saveEdit() }}>保存</button>
                        <button type="button" className="ghost" onClick={(e) => { e.stopPropagation(); setEditingIndex(null) }}>取消</button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="muted">#{p.index}</div>
                      <div className="paragraph-snippet">{(p.text || (p.is_table ? '[表格]' : '')).slice(0, 120)}{(p.text || '').length > 120 ? '…' : ''}</div>
                      <button type="button" className="ghost tiny" onClick={(e) => { e.stopPropagation(); startEdit(p) }}>编辑</button>
                    </>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
