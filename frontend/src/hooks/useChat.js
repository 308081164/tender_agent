import { useCallback, useState } from 'react'
import { api } from '../api/client'

export function useChatSessions(showToast) {
  const [open, setOpen] = useState(false)
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [chatInput, setChatInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [showHistory, setShowHistory] = useState(false)

  const refreshSessions = useCallback(async () => {
    const list = await api.listChatSessions()
    setSessions(list)
    return list
  }, [])

  const loadSession = useCallback(async (id) => {
    const data = await api.getChatSession(id)
    setSessionId(data.id)
    setMessages(data.messages || [])
    setShowHistory(false)
    return data
  }, [])

  const ensureSession = useCallback(async () => {
    if (sessionId) return sessionId
    const s = await api.createChatSession('新对话')
    setSessionId(s.id)
    setMessages([])
    await refreshSessions()
    return s.id
  }, [sessionId, refreshSessions])

  const openDrawer = useCallback(async () => {
    setOpen(true)
    try {
      const list = await refreshSessions()
      if (sessionId) {
        await loadSession(sessionId)
      } else if (list[0]) {
        await loadSession(list[0].id)
      }
    } catch (e) {
      showToast?.(e.message)
    }
  }, [refreshSessions, sessionId, loadSession, showToast])

  const closeDrawer = useCallback(() => setOpen(false), [])

  const newChat = useCallback(async () => {
    setLoading(true)
    try {
      const s = await api.createChatSession('新对话')
      setSessionId(s.id)
      setMessages([])
      setShowHistory(false)
      await refreshSessions()
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setLoading(false)
    }
  }, [refreshSessions, showToast])

  const askChat = useCallback(async () => {
    const q = chatInput.trim()
    if (!q || loading) return
    setChatInput('')
    setLoading(true)
    const optimistic = { role: 'user', content: q }
    setMessages((m) => [...m, optimistic])
    try {
      const id = await ensureSession()
      const res = await api.sendChatMessage(id, q)
      setMessages((m) => {
        const withoutOptimistic = m.filter((x) => x !== optimistic)
        return [
          ...withoutOptimistic,
          res.user_message,
          res.assistant_message,
        ]
      })
      if (res.session) {
        setSessions((list) => {
          const rest = list.filter((s) => s.id !== res.session.id)
          return [res.session, ...rest]
        })
      }
    } catch (e) {
      setMessages((m) => [
        ...m.filter((x) => x !== optimistic),
        optimistic,
        { role: 'assistant', content: `提问失败：${e.message}` },
      ])
    } finally {
      setLoading(false)
    }
  }, [chatInput, loading, ensureSession])

  return {
    open,
    openDrawer,
    closeDrawer,
    sessions,
    sessionId,
    messages,
    chatInput,
    setChatInput,
    loading,
    showHistory,
    setShowHistory,
    newChat,
    loadSession,
    askChat,
    refreshSessions,
  }
}
