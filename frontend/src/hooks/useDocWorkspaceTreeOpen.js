import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEY = 'docWorkspace.treeOpen'

function readStored(defaultOpen = false) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === '1' || raw === 'true') return true
    if (raw === '0' || raw === 'false') return false
  } catch {
    /* ignore */
  }
  return defaultOpen
}

export function useDocWorkspaceTreeOpen({ enabled = true } = {}) {
  const [treeOpen, setTreeOpenState] = useState(() => readStored(false))

  const setTreeOpen = useCallback((next) => {
    setTreeOpenState((prev) => {
      const value = typeof next === 'function' ? next(prev) : next
      try {
        localStorage.setItem(STORAGE_KEY, value ? '1' : '0')
      } catch {
        /* ignore */
      }
      return value
    })
  }, [])

  const toggleTree = useCallback(() => {
    if (!enabled) return
    setTreeOpen((v) => !v)
  }, [enabled, setTreeOpen])

  useEffect(() => {
    if (!enabled && treeOpen) setTreeOpen(false)
  }, [enabled, treeOpen, setTreeOpen])

  return { treeOpen: enabled && treeOpen, setTreeOpen, toggleTree }
}
