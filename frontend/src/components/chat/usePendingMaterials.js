import { useCallback, useRef, useState } from 'react'
import { typeLabel } from './chatTranscriptModel'

const LIMIT = 20

function trim(items) {
  return items.slice(0, LIMIT)
}

export function usePendingMaterials() {
  const [items, setItems] = useState([])
  const ref = useRef([])

  const commit = useCallback((updater) => {
    setItems((prev) => {
      const next = trim(typeof updater === 'function' ? updater(prev) : updater)
      ref.current = next
      return next
    })
  }, [])

  const addFiles = useCallback((files) => {
    const list = Array.from(files || []).filter(Boolean)
    if (!list.length) return
    commit((prev) => {
      const next = [...prev]
      for (const file of list) {
        const id = `file:${file.name}:${file.size}:${file.lastModified}`
        if (next.some((item) => item.id === id)) continue
        next.push({
          id,
          name: file.name,
          kind: 'file',
          type: typeLabel(file.name, 'file'),
          file,
        })
      }
      return next
    })
  }, [commit])

  const addFolderFiles = useCallback((files) => {
    const list = Array.from(files || []).filter(Boolean)
    if (!list.length) return
    const rel = list[0].webkitRelativePath || ''
    const name = rel.split(/[/\\]/)[0] || '文件夹'
    commit((prev) => [
      ...prev,
      {
        id: `dir:${name}:${list.length}:${Date.now()}`,
        name,
        kind: 'folder',
        type: '文件夹',
        files: list,
        count: list.length,
      },
    ])
  }, [commit])

  const addFolderPath = useCallback((folderPath, folderLabel) => {
    const path = String(folderPath || '').trim()
    if (!path) return
    const name = path.split(/[/\\]/).filter(Boolean).pop() || folderLabel || '文件夹'
    const id = `path:${path}`
    commit((prev) => {
      if (prev.some((item) => item.id === id)) return prev
      return [
        ...prev,
        {
          id,
          name,
          kind: 'folder',
          type: '文件夹',
          path,
          label: folderLabel || '选择资质文件夹',
        },
      ]
    })
  }, [commit])

  const remove = useCallback((id) => {
    commit((prev) => prev.filter((item) => item.id !== id))
  }, [commit])

  const clear = useCallback(() => {
    commit([])
  }, [commit])

  const consume = useCallback(() => {
    const taken = ref.current
    commit([])
    return taken
  }, [commit])

  const restore = useCallback((staged) => {
    if (!staged?.length) return
    commit((prev) => {
      const ids = new Set(prev.map((item) => item.id))
      return [...staged.filter((item) => !ids.has(item.id)), ...prev]
    })
  }, [commit])

  return {
    items,
    addFiles,
    addFolderFiles,
    addFolderPath,
    remove,
    clear,
    consume,
    restore,
  }
}
