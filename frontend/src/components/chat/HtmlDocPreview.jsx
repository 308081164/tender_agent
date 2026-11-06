import React, { useEffect, useRef, useState } from 'react'

/**
 * Aspose DOCX→HTML 高保真预览（内嵌 CSS/图片）。iframe 内脚本通过 postMessage 回传选区。
 */
export default function HtmlDocPreview({
  src,
  title = '文档预览',
  className = '',
  onSelectText,
  onSelectAnchor,
  onLoadError,
  iframeRef: iframeRefProp,
}) {
  const [failed, setFailed] = useState(false)
  const localRef = useRef(null)
  const iframeRef = iframeRefProp || localRef

  useEffect(() => {
    let cancelled = false
    setFailed(false)
    if (!src) return undefined

    const verify = async () => {
      try {
        const res = await fetch(src, { method: 'GET', credentials: 'same-origin' })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const type = (res.headers.get('content-type') || '').toLowerCase()
        const blob = await res.blob()
        if (cancelled) return
        if (!blob.size || blob.size < 80) throw new Error('empty html')
        if (type && !type.includes('html') && !type.includes('octet-stream')) {
          throw new Error('not html')
        }
      } catch {
        if (!cancelled) {
          setFailed(true)
          onLoadError?.()
        }
      }
    }
    verify()
    return () => { cancelled = true }
  }, [src, onLoadError])

  useEffect(() => {
    const handler = (ev) => {
      if (!ev.data || ev.data.source !== 'doc-html-preview') return
      if (ev.data.type !== 'doc-preview-select') return
      const text = (ev.data.selected_text || '').trim()
      if (text.length >= 2) onSelectText?.(text)
      onSelectAnchor?.({
        selected_text: text,
        paragraph_index: ev.data.paragraph_index,
        source: 'document',
      })
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [onSelectText, onSelectAnchor])

  if (!src || failed) return null
  return (
    <div className={`preview-doc preview-html ${className}`.trim()}>
      <iframe
        ref={iframeRef}
        className="preview-html-frame"
        title={title}
        src={src}
        sandbox="allow-scripts allow-same-origin allow-popups"
        onError={() => { setFailed(true); onLoadError?.() }}
      />
    </div>
  )
}

export function scrollHtmlPreviewToParagraph(iframeRef, paragraphIndex) {
  const win = iframeRef?.current?.contentWindow
  if (!win || paragraphIndex == null) return
  win.postMessage({ type: 'doc-preview-scroll', paragraph_index: paragraphIndex }, '*')
}
