import React, { useEffect, useState } from 'react'
import WorkspaceFileTree from './WorkspaceFileTree'

export default function WorkspaceTreeSlidePanel({
  open,
  onClose,
  sessionId,
  workspaceRootLabel,
  selectedPath,
  onSelectFile,
}) {
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    if (open) setRefreshToken((t) => t + 1)
  }, [open, workspaceRootLabel, sessionId])

  if (!open) return null

  return (
    <>
      <button type="button" className="ws-tree-backdrop" aria-label="关闭工程目录" onClick={onClose} />
      <aside className="ws-file-tree-slide" aria-label="工程目录">
        <div className="ws-tree-slide-head">
          <strong>工程目录</strong>
          <button type="button" className="ghost tiny" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>
        <WorkspaceFileTree
          sessionId={sessionId}
          workspaceRootLabel={workspaceRootLabel}
          selectedPath={selectedPath}
          onSelectFile={onSelectFile}
          refreshToken={refreshToken}
        />
      </aside>
    </>
  )
}
