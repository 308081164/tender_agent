import React from 'react'

export default function AdminFilePreview({ url, fileType, name, emptyText = '暂无附件' }) {
  if (!url) {
    return <div className="admin-file-preview empty">{emptyText}</div>
  }
  const ftype = (fileType || '').toLowerCase().replace('.', '')
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'].includes(ftype)) {
    return (
      <div className="admin-file-preview">
        <img src={url} alt={name || 'preview'} />
      </div>
    )
  }
  if (ftype === 'pdf') {
    return (
      <div className="admin-file-preview">
        <iframe title={name || 'pdf'} src={url} />
      </div>
    )
  }
  return (
    <div className="admin-file-preview empty">
      <p>{name || '附件'}</p>
      <a href={url} target="_blank" rel="noreferrer">下载查看</a>
    </div>
  )
}
