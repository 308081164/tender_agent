import React from 'react'

/**
 * High-fidelity DOCX preview via Aspose/LibreOffice → PDF.
 * Browser native PDF viewer provides page breaks matching Word pagination.
 */
export default function PdfPreview({ src, title = '文档预览', onLoadError }) {
  if (!src) return null
  return (
    <div className="preview-doc preview-pdf">
      <iframe
        className="preview-pdf-frame"
        title={title}
        src={src}
        onError={() => onLoadError?.()}
      />
    </div>
  )
}
