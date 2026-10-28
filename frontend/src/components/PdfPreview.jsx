import React, { useEffect, useState } from 'react'

/**
 * High-fidelity DOCX preview via Aspose/LibreOffice → PDF.
 * Browser native PDF viewer provides page breaks matching Word pagination.
 */
export default function PdfPreview({ src, title = '文档预览', className = '', onLoadError }) {
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    setFailed(false)
    if (!src) return undefined

    const verify = async () => {
      try {
        const res = await fetch(src, { method: 'GET', credentials: 'same-origin' })
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        const type = (res.headers.get('content-type') || '').toLowerCase()
        const blob = await res.blob()
        if (cancelled) return
        if (!blob.size || blob.size < 80) {
          throw new Error('empty pdf')
        }
        if (type && !type.includes('pdf') && !type.includes('octet-stream')) {
          throw new Error('not pdf')
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

  if (!src || failed) return null
  return (
    <div className={`preview-doc preview-pdf ${className}`.trim()}>
      <iframe
        className="preview-pdf-frame"
        title={title}
        src={src}
        onError={() => { setFailed(true); onLoadError?.() }}
      />
    </div>
  )
}
