import { useCallback, useRef, useState } from 'react'
import { api } from '../api/client'
import { appendStreamToken, keepStreamedReply } from '../components/chat/agentChatRuntime'
import { sessionFromProjectBind } from '../utils/projectSession'
import { deliverChatMaterials } from '../components/chat/deliverChatMaterials'
import { usePendingMaterials } from '../components/chat/usePendingMaterials'
import { useChatMentions } from './useChatMentions'

export function useChatSessions(showToast) {
  const [open, setOpen] = useState(false)
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [chatInput, setChatInput] = useState('')
  const [webSearch, setWebSearch] = useState(false)
  const [loading, setLoading] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [actingCardId, setActingCardId] = useState(null)
  const [chatContext, setChatContext] = useState(null)
  const [boundProjectId, setBoundProjectId] = useState(null)
  const [workspace, setWorkspace] = useState({})
  const [replyStreaming, setReplyStreaming] = useState(false)
  const materials = usePendingMaterials()
  const ensureSessionRef = useRef(null)
  const ensureForMentions = useCallback(() => ensureSessionRef.current?.(), [])
  const mentions = useChatMentions(sessionId, ensureForMentions)

  const refreshSessions = useCallback(async () => {
    const list = await api.listChatSessions()
    setSessions(list)
    return list
  }, [])

  const loadSession = useCallback(async (id) => {
    const data = await api.getChatSession(id)
    setSessionId(data.id)
    setMessages(data.messages || [])
    setWorkspace(data.workspace || {})
    materials.clear()
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
  ensureSessionRef.current = ensureSession

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
      setWorkspace({})
      materials.clear()
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

  const rememberSession = useCallback((session) => {
    if (!session) return
    if (session.workspace) setWorkspace(session.workspace)
    setSessions((list) => [session, ...list.filter((s) => s.id !== session.id)])
  }, [])

  const bindProjectSession = useCallback(async (projectId) => {
    if (!projectId) {
      setBoundProjectId(null)
      setChatContext(null)
      return null
    }
    setBoundProjectId(projectId)
    setChatContext({ project_id: projectId, guided_intake: true })
    try {
      const sess = sessionFromProjectBind(await api.ensureProjectSession(projectId))
      if (!sess?.id) throw new Error('未能绑定项目会话')
      setSessionId(sess.id)
      if (sess.workspace) setWorkspace(sess.workspace)
      await refreshSessions()
      const data = await api.getChatSession(sess.id)
      setMessages(data.messages || [])
      if (data.workspace) setWorkspace(data.workspace)
      return sess.id
    } catch (e) {
      showToast?.(e.message)
      return null
    }
  }, [refreshSessions, showToast])

  const askChat = useCallback(async () => {
    if (loading) return
    const q = chatInput.trim()
    const staged = materials.consume()
    const sentMentions = mentions.mentions
    if (!q && !staged.length && !sentMentions.length) return
    const draft = chatInput
    setChatInput('')
    setLoading(true)
    const optimisticId = `tmp-${Date.now()}`
    const assistantId = `tmp-bot-${Date.now()}`
    const optimistic = {
      id: optimisticId,
      role: 'user',
      content: q,
      metadata: {
        ...(staged.length ? { attachments: staged.map(({ name, kind, type }) => ({ name, kind, type })) } : {}),
        ...(sentMentions.length ? { mentions: sentMentions } : {}),
      },
    }
    mentions.clearMentions()
    setMessages((m) => [...m, optimistic])
    let delivered = []
    try {
      const id = await ensureSession()
      if (staged.length) {
        const uploaded = await deliverChatMaterials(api, id, staged)
        delivered = uploaded.messages
        rememberSession(uploaded.session)
        if (uploaded.workspace) setWorkspace(uploaded.workspace)
      }
      let textTurn = []
      if (q || sentMentions.length) {
        setReplyStreaming(true)
        setMessages((m) => [
          ...m.filter((x) => x.id !== optimisticId),
          ...delivered,
          { id: optimisticId, role: 'user', content: q, metadata: optimistic.metadata },
          { id: assistantId, role: 'assistant', content: '' },
        ])
        const ctx = { ...(chatContext || {}) }
        if (webSearch) ctx.web_search = true
        if (sentMentions.length) ctx.mentions = sentMentions
        const res = await api.sendChatMessageStream(id, q, ctx, (tok, event) => {
          setMessages((m) => m.map((x) => (
            x.id === assistantId ? appendStreamToken(x, tok, event) : x
          )))
        })
        if (res.user_message) textTurn.push(res.user_message)
        if (res.assistant_message) textTurn.push(res.assistant_message)
        rememberSession(res.session)
      }
      setMessages((m) => {
        const base = m.filter((x) => x.id !== optimisticId && x.id !== assistantId)
        const already = delivered[0]?.id && base.some((item) => item.id === delivered[0].id)
        return [...(already ? base : [...base, ...delivered]), ...textTurn]
      })
    } catch (e) {
      setMessages((m) => {
        const partial = m.find((x) => x.id === assistantId)
        const kept = keepStreamedReply(partial?.content, e.message)
        const base = m.filter((x) => x.id !== optimisticId && x.id !== assistantId)
        const already = delivered[0]?.id && base.some((item) => item.id === delivered[0].id)
        return [
          ...(already ? base : [...base, ...delivered]),
          optimistic,
          {
            id: assistantId,
            role: 'assistant',
            content: kept,
            metadata: { ...(partial?.metadata || {}), stream_error: e.message },
          },
        ]
      })
      if (!delivered.length) materials.restore(staged)
      showToast?.(e.message)
    } finally {
      setReplyStreaming(false)
      setLoading(false)
    }
  }, [chatInput, loading, materials, mentions, ensureSession, chatContext, webSearch, rememberSession, showToast])

  const patchWorkspaceDir = useCallback(async (dir) => {
    try {
      const id = await ensureSession()
      const updated = await api.patchChatSessionWorkspace(id, { workspace_dir: dir || '' })
      setWorkspace(updated.workspace || {})
      return updated
    } catch (e) {
      showToast?.(e.message)
      return null
    }
  }, [ensureSession, showToast])

  return {
    open,
    openDrawer,
    closeDrawer,
    sessions,
    sessionId,
    messages,
    chatInput,
    setChatInput,
    webSearch,
    setWebSearch,
    loading,
    showHistory,
    setShowHistory,
    newChat,
    loadSession,
    askChat,
    refreshSessions,
    handleCardAction,
    actingCardId,
    pendingMaterials: materials.items,
    removePendingMaterial: materials.remove,
    stageFiles: materials.addFiles,
    stageFolderFiles: materials.addFolderFiles,
    stageFolderPath: materials.addFolderPath,
    replyStreaming,
    showToast,
    bindProjectSession,
    boundProjectId,
    chatContext,
    workspace,
    patchWorkspaceDir,
    mentions: mentions.mentions,
    mentionItems: mentions.mentionItems,
    onMentionQuery: mentions.onMentionQuery,
    pickMention: mentions.pickMention,
    removeMention: mentions.removeMention,
  }
}
