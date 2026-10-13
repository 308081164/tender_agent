import React, { useRef, useState } from 'react'

const MULTI_ACCEPT =
  '.pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff,.zip'

/**
 * 附件区：明确二选一 — 多个文件 / 整个文件夹（桌面选目录或 Web 选目录/zip）
 */
export default function ChatAttachmentControls({
  disabled,
  onUploadFiles,
  onImportFolderPath,
  onImportFolderZip,
  showToast,
  compact = false,
}) {
  const multiRef = useRef(null)
  const folderRef = useRef(null)
  const zipRef = useRef(null)
  const [menuOpen, setMenuOpen] = useState(false)

  const desktop = typeof window !== 'undefined' ? window.tenderAgentDesktop : null

  const pickFolderDesktop = async () => {
    setMenuOpen(false)
    if (!desktop?.pickQualFolder) {
      showToast?.('Web 端请使用「文件夹 (浏览器)」或上传 zip 压缩包')
      return
    }
    try {
      const res = await desktop.pickQualFolder()
      if (!res?.canceled && res.path) {
        await onImportFolderPath?.(res.path, '选择资质文件夹')
      }
    } catch (e) {
      showToast?.(e.message || '无法打开文件夹选择器')
    }
  }

  const onMultiChange = async (e) => {
    const list = Array.from(e.target.files || [])
    e.target.value = ''
    setMenuOpen(false)
    if (list.length && onUploadFiles) {
      await onUploadFiles(list)
    }
  }

  const onFolderInputChange = async (e) => {
    const list = Array.from(e.target.files || [])
    e.target.value = ''
    setMenuOpen(false)
    if (!list.length || !onUploadFiles) return
    await onUploadFiles(list)
  }

  const onZipChange = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    setMenuOpen(false)
    if (file && onImportFolderZip) {
      await onImportFolderZip(file)
    } else if (file && onUploadFiles) {
      await onUploadFiles([file])
    }
  }

  return (
    <div className={`chat-attach-wrap${compact ? ' compact' : ''}`}>
      <input
        ref={multiRef}
        type="file"
        className="hidden"
        multiple
        accept={MULTI_ACCEPT}
        onChange={onMultiChange}
      />
      <input
        ref={folderRef}
        type="file"
        className="hidden"
        webkitdirectory=""
        directory=""
        multiple
        onChange={onFolderInputChange}
      />
      <input ref={zipRef} type="file" className="hidden" accept=".zip" onChange={onZipChange} />

      <button
        type="button"
        className="ghost chat-attach-trigger"
        disabled={disabled}
        title="添加附件"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((v) => !v)}
      >
        📎
      </button>

      {menuOpen ? (
        <>
          <div className="chat-attach-menu-backdrop" onClick={() => setMenuOpen(false)} />
          <div className="chat-attach-menu" role="menu">
            <button
              type="button"
              role="menuitem"
              onClick={() => multiRef.current?.click()}
              disabled={disabled}
            >
              <strong>多个文件</strong>
              <span className="muted">pdf / docx / txt / 图片 / zip</span>
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={pickFolderDesktop}
              disabled={disabled}
            >
              <strong>整个文件夹</strong>
              <span className="muted">桌面版系统目录选择器</span>
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => folderRef.current?.click()}
              disabled={disabled}
            >
              <strong>文件夹 (浏览器)</strong>
              <span className="muted">Chrome / Edge 选目录上传</span>
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => zipRef.current?.click()}
              disabled={disabled}
            >
              <strong>文件夹 (zip)</strong>
              <span className="muted">解压后按资质包导入</span>
            </button>
          </div>
        </>
      ) : null}
    </div>
  )
}
