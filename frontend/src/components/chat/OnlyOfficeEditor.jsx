import React, { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'

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
      reject(new Error('无法加载 OnlyOffice 编辑器脚本'))
    }
    document.body.appendChild(script)
  })
  return scriptPromise
}

export default function OnlyOfficeEditor({ sessionId, workspace, onSaved }) {
  const containerRef = useRef(null)
  const editorRef = useRef(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const version = workspace?.version || 1
  const docKey = workspace?.draft_object_key || workspace?.template_object_key

  useEffect(() => {
    if (!sessionId || !docKey) return undefined

    let cancelled = false
    const mount = async () => {
      setLoading(true)
      setError('')
      try {
        const data = await api.getOnlyOfficeConfig(sessionId)
        if (cancelled) return
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
            onDocumentStateChange: (event) => {
              if (event?.data) {
                // 文档有未保存修改
              }
            },
            onRequestClose: () => onSaved?.(),
            onError: (event) => {
              setError(event?.data || 'OnlyOffice 编辑器错误')
            },
          },
        })
        editorRef.current = editor
      } catch (e) {
        if (!cancelled) setError(e.message || '加载编辑器失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    mount()
    return () => {
      cancelled = true
      if (editorRef.current?.destroyEditor) {
        editorRef.current.destroyEditor()
        editorRef.current = null
      }
    }
  }, [sessionId, docKey, version, onSaved])

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
