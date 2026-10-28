import React, { useEffect, useState } from 'react'
import PdfPreview from '../PdfPreview'
import SelectableDocPreview from '../admin/SelectableDocPreview'
import OnlyOfficeEditor from './OnlyOfficeEditor'

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

  const hasDoc = !!(workspace?.draft_object_key || workspace?.template_object_key)
  const hasParagraphs = (paragraphs || []).some((p) => (p.text || '').trim().length > 0)
  const pdfSrc = hasDoc && sessionId ? `/api/chat/sessions/${sessionId}/workspace/preview.pdf` : null

  useEffect(() => {
    setPdfFailed(false)
    setOnlyOfficeFailed(false)
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
            {!hasParagraphs && hasDoc ? (
              <div className="doc-workspace-empty">
                <p className="muted">PDF/OnlyOffice 暂不可用，且未能解析段落。请尝试「下载 DOCX」本地打开，或稍后重试预览。</p>
              </div>
            ) : null}
            <SelectableDocPreview
              paragraphs={paragraphs}
              mappings={[]}
              selectedText={selectedText}
              onSelectText={onSelectText}
              onSelectAnchor={onSelectAnchor}
              reviewHighlightTexts={highlightTexts}
            />
            <div className="paragraph-edit-list">
              <h4>段落快速编辑</h4>
              {(paragraphs || []).slice(0, 40).map((p) => (
                <div key={p.index} className="paragraph-edit-row">
                  {editingIndex === p.index ? (
                    <>
                      <textarea value={editText} onChange={(e) => setEditText(e.target.value)} rows={3} />
                      <div className="row-actions">
                        <button type="button" onClick={saveEdit}>保存</button>
                        <button type="button" className="ghost" onClick={() => setEditingIndex(null)}>取消</button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="muted">#{p.index}</div>
                      <div className="paragraph-snippet">{(p.text || '').slice(0, 120)}{(p.text || '').length > 120 ? '…' : ''}</div>
                      <button type="button" className="ghost tiny" onClick={() => startEdit(p)}>编辑</button>
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
