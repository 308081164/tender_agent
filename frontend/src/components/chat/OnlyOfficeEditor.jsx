import React, { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import { applyOnlyOfficeHighlights, bindOnlyOfficeSelection } from './agentChatRuntime'

let scriptPromise = null

function loadOnlyOfficeApi(documentServerUrl) {
  if (typeof window !== 'undefined' && window.DocsAPI) {
    return Promise.resolve()
  }
  if (scriptPromise) return scriptPromise
  scriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `${documentServerUrl.replace(/\/$/, '')}/web-apps/apps/api/documents/api.js`
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => {
      scriptPromise = null
      reject(new Error(`无法加载内置 OnlyOffice 编辑器（${documentServerUrl}）`))
    }
    document.body.appendChild(script)
  })
  return scriptPromise
}

function subscribeOnlyOfficeSelection(editor, onAnchor, highlights) {
  if (!editor) return
  try {
    const connector = editor.createConnector?.()
    if (!connector) return
    if (onAnchor) bindOnlyOfficeSelection(connector, onAnchor)
    applyOnlyOfficeHighlights(connector, highlights)
  } catch {
    // 编辑器未就绪时不把光标默认为文首。
  }
}

export default function OnlyOfficeEditor({
  sessionId,
  workspace,
  onSaved,
  onAnchor,
  highlightTexts = [],
  onUnavailable,
}) {
  const containerRef = useRef(null)
  const editorRef = useRef(null)
  const onAnchorRef = useRef(onAnchor)
  const highlightRef = useRef(highlightTexts)
  onAnchorRef.current = onAnchor
  highlightRef.current = highlightTexts
  const highlightKey = (highlightTexts || []).join('\u0001')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const version = workspace?.version || 1
  const docKey = workspace?.draft_object_key || workspace?.template_object_key

  useEffect(() => {
    if (!sessionId || !docKey) return undefined

    let cancelled = false
    let loadTimer = null
    const mount = async () => {
      setLoading(true)
      setError('')
      try {
        const data = await api.getOnlyOfficeConfig(sessionId)
        if (cancelled) return
        if (!data?.document_server_url) {
          throw new Error(data?.message || '内置 OnlyOffice 未配置，无法打开可编辑文档')
        }
        await loadOnlyOfficeApi(data.document_server_url)
        if (cancelled || !containerRef.current) return

        if (editorRef.current?.destroyEditor) {
          editorRef.current.destroyEditor()
          editorRef.current = null
        }
        containerRef.current.innerHTML = ''

        const editor = new window.DocsAPI.DocEditor(containerRef.current, {
          ...data.config,
          events: {
            onDocumentReady: () => subscribeOnlyOfficeSelection(editor, onAnchorRef.current, highlightRef.current),
            onDocumentStateChange: (event) => {
              if (event?.data) subscribeOnlyOfficeSelection(editor, onAnchorRef.current, highlightRef.current)
            },
            onRequestClose: () => onSaved?.(),
            onError: (event) => {
              const msg = event?.data || 'OnlyOffice 编辑器错误'
              setError(msg)
              onUnavailable?.(msg)
            },
          },
        })
        editorRef.current = editor
        subscribeOnlyOfficeSelection(editor, onAnchorRef.current, highlightRef.current)
        loadTimer = window.setTimeout(() => {
          if (!cancelled && containerRef.current && !containerRef.current.querySelector('iframe')) {
            const msg = 'OnlyOffice 未加载文档，已切换预览模式'
            setError(msg)
            onUnavailable?.(msg)
          }
        }, 12000)
      } catch (e) {
        if (!cancelled) {
          const msg = e.message || '加载编辑器失败'
          setError(msg)
          onUnavailable?.(msg)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    mount()
    return () => {
      cancelled = true
      if (loadTimer) window.clearTimeout(loadTimer)
      if (editorRef.current?.destroyEditor) {
        editorRef.current.destroyEditor()
        editorRef.current = null
      }
    }
  }, [sessionId, docKey, version, onSaved, onUnavailable])

  useEffect(() => {
    const timer = window.setInterval(() => {
      subscribeOnlyOfficeSelection(editorRef.current, onAnchorRef.current, highlightRef.current)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [sessionId, docKey, highlightKey])

  if (!docKey) {
    return <div className="onlyoffice-empty muted">请先上传 DOCX 文档</div>
  }

  return (
    <div className="onlyoffice-pane">
      {loading ? <div className="onlyoffice-loading muted">正在加载 Word 编辑器…</div> : null}
      {error ? <div className="onlyoffice-error">{error}</div> : null}
      <div ref={containerRef} className="onlyoffice-editor-host" />
    </div>
  )
}
