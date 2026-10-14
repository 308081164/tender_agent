import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'

export function useChatMentions(sessionId, ensureSession) {
  const [mentions, setMentions] = useState([])
  const [items, setItems] = useState([])
  const [query, setQuery] = useState(null)

  const onMentionQuery = useCallback((active) => {
    setQuery(active ? active.query : null)
  }, [])

  useEffect(() => {
    if (query === null) {
      setItems([])
      return undefined
    }
    let cancelled = false
    ;(async () => {
      let id = sessionId
      if (!id && ensureSession) {
        try { id = await ensureSession() } catch { id = null }
      }
      if (!id || cancelled) {
        if (!cancelled) setItems([])
        return
      }
      try {
        const res = await api.listChatMentions(id, query)
        if (!cancelled) setItems(res.items || [])
      } catch {
        if (!cancelled) setItems([])
      }
    })()
    return () => { cancelled = true }
  }, [sessionId, query, ensureSession])

  const pickMention = useCallback((item) => {
    if (!item?.label) return
    setMentions((list) => {
      const key = `${item.kind}:${item.section_id || item.path || item.label}`
      if (list.some((row) => `${row.kind}:${row.section_id || row.path || row.label}` === key)) return list
      return [...list, item]
    })
  }, [])

  const removeMention = useCallback((item) => {
    setMentions((list) => list.filter((row) => row !== item && (
      `${row.kind}:${row.section_id || row.path || row.label}`
      !== `${item.kind}:${item.section_id || item.path || item.label}`
    )))
  }, [])

  const clearMentions = useCallback(() => setMentions([]), [])

  return {
    mentions,
    mentionItems: query === null ? [] : items,
    onMentionQuery,
    pickMention,
    removeMention,
    clearMentions,
  }
}
