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
  const [actingCardId, setActingCardId] = useState(null)

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

  const handleCardAction = useCallback(async (message, card, action, payload) => {
    if (actingCardId || loading) return
    setActingCardId(card.id)
    try {
      const id = await ensureSession()
      const res = await api.sendChatAction(id, {
        message_id: message.id,
        card_id: card.id,
        action,
        payload: payload || {},
      })
      setMessages((list) => {
        const next = list.map((m) => (
          m.id && res.acted_message && m.id === res.acted_message.id ? res.acted_message : m
        ))
        if (res.user_message) next.push(res.user_message)
        if (res.assistant_message) next.push(res.assistant_message)
        return next
      })
      if (res.session) {
        setSessions((list) => [res.session, ...list.filter((s) => s.id !== res.session.id)])
      }
    } catch (e) {
      showToast?.(e.message)
    } finally {
      setActingCardId(null)
    }
  }, [actingCardId, loading, ensureSession, showToast])

  const mergeUploadResponse = useCallback((res, optimisticId) => {
    setMessages((m) => [
      ...m.filter((x) => x.id !== optimisticId),
      res.user_message,
      res.assistant_message,
    ])
    if (res.session) {
      setSessions((list) => [res.session, ...list.filter((s) => s.id !== res.session.id)])
    }
  }, [])

  const uploadFiles = useCallback(async (files) => {
    const list = Array.from(files || []).filter(Boolean)
    if (!list.length || loading) return
    const label =
      list.length === 1
        ? `[上传文件] ${list[0].name}`
        : `[上传 ${list.length} 个文件] ${list.map((f) => f.name).slice(0, 3).join('、')}${list.length > 3 ? '…' : ''}`
    const optimisticId = `tmp-file-${Date.now()}`
    setMessages((m) => [...m, { id: optimisticId, role: 'user', content: label }])
    setLoading(true)
    try {
      const id = await ensureSession()
      const res =
        list.length === 1
          ? await api.uploadChatFile(id, list[0])
          : await api.uploadChatFilesBatch(id, list)
      mergeUploadResponse(res, optimisticId)
    } catch (e) {
      showToast?.(e.message)
      setMessages((m) => m.filter((x) => x.id !== optimisticId))
    } finally {
      setLoading(false)
    }
  }, [loading, ensureSession, mergeUploadResponse, showToast])

  const importFolderPath = useCallback(async (folderPath, folderLabel) => {
    if (!folderPath || loading) return
    const optimisticId = `tmp-folder-${Date.now()}`
    const userLine = `[${folderLabel || '选择文件夹'}] ${folderPath}`
    setMessages((m) => [...m, { id: optimisticId, role: 'user', content: userLine }])
    setLoading(true)
    try {
      const id = await ensureSession()
      const res = await api.importChatFolder(id, folderPath, folderLabel)
      mergeUploadResponse(res, optimisticId)
    } catch (e) {
      showToast?.(e.message)
      setMessages((m) => m.filter((x) => x.id !== optimisticId))
    } finally {
      setLoading(false)
    }
  }, [loading, ensureSession, mergeUploadResponse, showToast])

  const askChat = useCallback(async () => {
    const q = chatInput.trim()
    if (!q || loading) return
    setChatInput('')
    setLoading(true)
    const optimisticId = `tmp-${Date.now()}`
    const optimistic = { id: optimisticId, role: 'user', content: q }
    setMessages((m) => [...m, optimistic])
    try {
      const id = await ensureSession()
      const res = await api.sendChatMessage(id, q)
      setMessages((m) => {
        const withoutOptimistic = m.filter((x) => x.id !== optimisticId)
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
        ...m.filter((x) => x.id !== optimisticId),
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
    handleCardAction,
    actingCardId,
    uploadFiles,
    importFolderPath,
    showToast,
  }
}
