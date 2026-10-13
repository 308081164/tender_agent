import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  formatWorkspaceDirLabel,
  pushRecentWorkspaceDir,
  readRecentWorkspaceDirs,
} from '../../utils/recentWorkspaceDirs'

function ContextPill({ label, value, active, onClick, title }) {
  return (
    <button
      type="button"
      className={`composer-ctx-pill${active ? ' open' : ''}`}
      onClick={onClick}
      title={title || value}
    >
      <span className="composer-ctx-pill-label">{label}</span>
      <span className="composer-ctx-pill-value">{value}</span>
      <span className="composer-ctx-pill-chevron" aria-hidden>▾</span>
    </button>
  )
}

function DropdownPanel({ open, onClose, children, className = '' }) {
  if (!open) return null
  return (
    <>
      <div className="composer-ctx-backdrop" onClick={onClose} />
      <div className={`composer-ctx-dropdown${className ? ` ${className}` : ''}`} role="listbox">
        {children}
      </div>
    </>
  )
}

export default function ComposerContextBar({
  workspaceDir = '',
  onWorkspaceDirChange,
  disabled = false,
  showProjectPicker = false,
  projects = [],
  projectId = null,
  onProjectChange,
  currentFile = null,
  onClearFile,
  fileLoading = false,
}) {
  const [dirOpen, setDirOpen] = useState(false)
  const [projOpen, setProjOpen] = useState(false)
  const [dirQuery, setDirQuery] = useState('')
  const dirInputRef = useRef(null)

  const recents = useMemo(() => readRecentWorkspaceDirs(), [dirOpen])
  const dirLabel = formatWorkspaceDirLabel(workspaceDir)

  const filteredRecents = useMemo(() => {
    const q = dirQuery.trim().toLowerCase()
    if (!q) return recents
    return recents.filter((d) => d.toLowerCase().includes(q))
  }, [recents, dirQuery])

  useEffect(() => {
    if (dirOpen && dirInputRef.current) dirInputRef.current.focus()
  }, [dirOpen])

  const pickDir = async (path) => {
    if (!path || disabled) return
    pushRecentWorkspaceDir(path)
    setDirOpen(false)
    setDirQuery('')
    await onWorkspaceDirChange?.(path)
  }

  const pickFolderNative = async () => {
    setDirOpen(false)
    const desktop = typeof window !== 'undefined' ? window.tenderAgentDesktop : null
    if (!desktop?.pickProjectWorkspaceDir) return
    try {
      const res = await desktop.pickProjectWorkspaceDir()
      if (!res?.canceled && res.path) await pickDir(res.path)
    } catch {
      /* caller may toast */
    }
  }

  const boundProject = projects.find((p) => p.id === projectId)
  const projectLabel = boundProject
    ? ((boundProject.fields?.project_name || boundProject.title || `项目 #${projectId}`).slice(0, 28))
    : '不在项目中'

  return (
    <div className="composer-context-bar">
      <div className="composer-context-pills">
        <div className="composer-ctx-pill-wrap">
          <ContextPill
            label="工作目录"
            value={dirLabel}
            active={dirOpen}
            onClick={() => !disabled && setDirOpen((v) => !v)}
            title={workspaceDir || '使用系统默认 Agent 工程目录'}
          />
          <DropdownPanel open={dirOpen} onClose={() => setDirOpen(false)}>
            <input
              ref={dirInputRef}
              type="search"
              className="composer-ctx-search"
              placeholder="搜索最近路径…"
              value={dirQuery}
              onChange={(e) => setDirQuery(e.target.value)}
            />
            <button type="button" className="composer-ctx-item primary" onClick={pickFolderNative}>
              <strong>选择文件夹</strong>
              <span className="muted tiny">桌面版系统目录选择器</span>
            </button>
            {filteredRecents.length ? (
              <div className="composer-ctx-section">最近使用</div>
            ) : null}
            {filteredRecents.map((d) => (
              <button key={d} type="button" className="composer-ctx-item" onClick={() => pickDir(d)}>
                {formatWorkspaceDirLabel(d)}
                <span className="muted tiny">{d}</span>
              </button>
            ))}
            <button
              type="button"
              className="composer-ctx-item ghost"
              onClick={() => pickDir('')}
            >
              恢复默认目录
            </button>
          </DropdownPanel>
        </div>

        {showProjectPicker ? (
          <div className="composer-ctx-pill-wrap">
            <ContextPill
              label="标书项目"
              value={projectLabel}
              active={projOpen}
              onClick={() => !disabled && setProjOpen((v) => !v)}
            />
            <DropdownPanel open={projOpen} onClose={() => setProjOpen(false)}>
              <button
                type="button"
                className="composer-ctx-item"
                onClick={() => { setProjOpen(false); onProjectChange?.(null) }}
              >
                不在项目中
              </button>
              {(projects || []).slice(0, 12).map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={`composer-ctx-item${p.id === projectId ? ' active' : ''}`}
                  onClick={() => { setProjOpen(false); onProjectChange?.(p.id) }}
                >
                  {(p.fields?.project_name || p.title || `项目 #${p.id}`).slice(0, 40)}
                </button>
              ))}
            </DropdownPanel>
          </div>
        ) : null}

        {currentFile?.path ? (
          <div className="composer-ctx-file-chip">
            {fileLoading ? (
              <span>正在读取…</span>
            ) : (
              <span>
                已载入 <em>{currentFile.path.split('/').pop()}</em>
                {currentFile.charCount != null ? ` (${currentFile.charCount} 字)` : ''}
              </span>
            )}
            <button type="button" className="ghost tiny" onClick={onClearFile} aria-label="清除文件上下文">
              ×
            </button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
