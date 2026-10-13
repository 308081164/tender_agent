import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../../api/client'

function TreeNode({
  sessionId,
  entry,
  depth,
  selectedPath,
  onSelectFile,
  expandedPaths,
  onToggleExpand,
  childrenCache,
  setChildrenCache,
}) {
  const isDir = entry.type === 'dir'
  const isExpanded = expandedPaths.has(entry.path)
  const isActive = !isDir && selectedPath === entry.path
  const children = childrenCache[entry.path]

  useEffect(() => {
    if (!isDir || !isExpanded || children !== undefined || !sessionId) return
    let cancelled = false
    ;(async () => {
      try {
        const data = await api.listWorkspaceTree(sessionId, entry.path)
        if (!cancelled) {
          setChildrenCache((prev) => ({ ...prev, [entry.path]: data.entries || [] }))
        }
      } catch {
        if (!cancelled) {
          setChildrenCache((prev) => ({ ...prev, [entry.path]: [] }))
        }
      }
    })()
    return () => { cancelled = true }
  }, [isDir, isExpanded, entry.path, sessionId, children, setChildrenCache])

  const pad = 8 + depth * 14

  return (
    <>
      <button
        type="button"
        className={`ws-tree-row${isActive ? ' active' : ''}`}
        style={{ paddingLeft: pad }}
        onClick={() => {
          if (isDir) onToggleExpand(entry.path)
          else onSelectFile(entry.path)
        }}
      >
        {isDir ? (
          <span className="ws-tree-chevron" aria-hidden>{isExpanded ? '▾' : '▸'}</span>
        ) : (
          <span className="ws-tree-chevron placeholder" aria-hidden />
        )}
        <span className="ws-tree-icon" aria-hidden>{isDir ? '📁' : '📄'}</span>
        <span className="ws-tree-name">{entry.name}</span>
      </button>
      {isDir && isExpanded && (children || []).map((child) => (
        <TreeNode
          key={child.path}
          sessionId={sessionId}
          entry={child}
          depth={depth + 1}
          selectedPath={selectedPath}
          onSelectFile={onSelectFile}
          expandedPaths={expandedPaths}
          onToggleExpand={onToggleExpand}
          childrenCache={childrenCache}
          setChildrenCache={setChildrenCache}
        />
      ))}
    </>
  )
}

export default function WorkspaceFileTree({
  sessionId,
  workspaceRootLabel,
  selectedPath,
  onSelectFile,
}) {
  const [rootEntries, setRootEntries] = useState([])
  const [loading, setLoading] = useState(false)
  const [expandedPaths, setExpandedPaths] = useState(() => new Set())
  const [childrenCache, setChildrenCache] = useState({})

  const refreshRoot = useCallback(async () => {
    if (!sessionId) return
    setLoading(true)
    try {
      const data = await api.listWorkspaceTree(sessionId, '')
      setRootEntries(data.entries || [])
      setChildrenCache({})
      setExpandedPaths(new Set())
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => {
    refreshRoot()
  }, [refreshRoot, workspaceRootLabel])

  const onToggleExpand = (path) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const rootName = workspaceRootLabel?.split(/[/\\]/).filter(Boolean).slice(-1)[0] || 'project'

  return (
    <div className="ws-file-tree">
      <div className="ws-tree-head">
        <strong>{rootName}/</strong>
        <button type="button" className="ghost tiny" onClick={refreshRoot} disabled={loading} title="刷新">
          ↻
        </button>
      </div>
      <div className="ws-tree-body">
        {loading && rootEntries.length === 0 ? (
          <p className="muted tiny">加载目录…</p>
        ) : null}
        {rootEntries.map((entry) => (
          <TreeNode
            key={entry.path}
            sessionId={sessionId}
            entry={entry}
            depth={0}
            selectedPath={selectedPath}
            onSelectFile={onSelectFile}
            expandedPaths={expandedPaths}
            onToggleExpand={onToggleExpand}
            childrenCache={childrenCache}
            setChildrenCache={setChildrenCache}
          />
        ))}
      </div>
    </div>
  )
}
