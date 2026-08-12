import React, { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api/client'
import ChatMessageBubble from '../components/chat/ChatMessageBubble'
import ChatFeatureCards from '../components/chat/ChatFeatureCards'
import { formatTime } from '../utils/format'

export default function ChatPage() {
  const { showToast } = useApp()
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [features, setFeatures] = useState({ feature_cards: [], suggested_prompts: [] })
  const [renamingId, setRenamingId] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const fileRef = useRef(null)
  const bottomRef = useRef(null)

  const refreshSessions = async () => {
    const list = await api.listChatSessions()
    setSessions(list)
    return list
  }

  const loadSession = async (id) => {
    const data = await api.getChatSession(id)
    setSessionId(data.id)
    setMessages(data.messages || [])
  }

  useEffect(() => {
    ;(async () => {
      try {
        const [list, feat] = await Promise.all([
          refreshSessions(),
          api.getChatFeatures(),
        ])
        setFeatures(feat)
        if (list[0]) await loadSession(list[0].id)
      } catch (e) {
        showToast(e.message)
      }
    })()
  }, [showToast])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const ensureSession = async () => {
    if (sessionId) return sessionId
    const s = await api.createChatSession('新对话')
    setSessionId(s.id)
    setMessages([])
    await refreshSessions()
    return s.id
  }

  const send = async (text) => {
    const q = (text ?? input).trim()
    if (!q || loading) return
    setInput('')
    setLoading(true)
    const optimistic = { role: 'user', content: q }
    setMessages((m) => [...m, optimistic])
    try {
      const id = await ensureSession()
      const res = await api.sendChatMessage(id, q)
      setMessages((m) => [
        ...m.filter((x) => x !== optimistic),
        res.user_message,
        res.assistant_message,
      ])
      if (res.session) {
        setSessions((list) => [res.session, ...list.filter((s) => s.id !== res.session.id)])
      }
    } catch (e) {
      setMessages((m) => [
        ...m.filter((x) => x !== optimistic),
        optimistic,
        { role: 'assistant', content: `发送失败：${e.message}` },
      ])
    } finally {
      setLoading(false)
    }
  }

  const newChat = async () => {
    const s = await api.createChatSession('新对话')
    setSessionId(s.id)
    setMessages([])
    await refreshSessions()
  }

  const deleteSession = async (id, e) => {
    e?.stopPropagation()
    if (!window.confirm('确定删除此对话？')) return
    await api.deleteChatSession(id)
    const list = await refreshSessions()
    if (sessionId === id) {
      if (list[0]) await loadSession(list[0].id)
      else {
        setSessionId(null)
        setMessages([])
      }
    }
  }

  const startRename = (s, e) => {
    e.stopPropagation()
    setRenamingId(s.id)
    setRenameValue(s.title || '')
  }

  const commitRename = async (id) => {
    const title = renameValue.trim()
    if (!title) return showToast('标题不能为空')
    const updated = await api.renameChatSession(id, title)
    setRenamingId(null)
    setSessions((list) => list.map((s) => (s.id === id ? { ...s, ...updated } : s)))
  }

  const uploadFile = async (file) => {
    if (!file || loading) return
    setLoading(true)
    try {
      const id = await ensureSession()
      const res = await api.uploadChatFile(id, file)
      setMessages((m) => [...m, res.user_message, res.assistant_message])
      if (res.session) {
        setSessions((list) => [res.session, ...list.filter((s) => s.id !== res.session.id)])
      }
    } catch (e) {
      showToast(e.message)
    } finally {
      setLoading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="chat-page">
      <aside className="chat-sidebar">
        <div className="chat-sidebar-head">
          <Link to="/" className="ghost">← 返回</Link>
          <button type="button" onClick={newChat}>新对话</button>
        </div>
        <div className="chat-session-list">
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`chat-session-item ${sessionId === s.id ? 'active' : ''}`}
              onClick={() => loadSession(s.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && loadSession(s.id)}
            >
              {renamingId === s.id ? (
                <input
                  className="chat-rename-input"
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onBlur={() => commitRename(s.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename(s.id)
                    if (e.key === 'Escape') setRenamingId(null)
                  }}
                  onClick={(e) => e.stopPropagation()}
                  autoFocus
                />
              ) : (
                <>
                  <strong>{s.title || `会话 #${s.id}`}</strong>
                  <span>{formatTime(s.updated_at || s.created_at)}</span>
                </>
              )}
              <div className="chat-session-actions">
                <button type="button" className="ghost tiny" onClick={(e) => startRename(s, e)} title="重命名">✎</button>
                <button type="button" className="ghost tiny" onClick={(e) => deleteSession(s.id, e)} title="删除">×</button>
              </div>
            </div>
          ))}
        </div>
      </aside>

      <main className="chat-main">
        <header className="chat-main-head">
          <h2>智能助手</h2>
          <p className="muted">通过自然语言完成模板创建、信息检索、标书初版等工作；复杂编辑请通过功能卡片跳转。</p>
        </header>

        <div className="chat-messages-area">
          {messages.length === 0 && !loading ? (
            <div className="chat-empty">
              <h3>你好，我是标书智能助手</h3>
              <p className="muted">我可以帮你新建标书、检索企业资质、指导模板创建，或解答投标相关问题。</p>
              <ChatFeatureCards cards={features.feature_cards} />
              <div className="chat-prompt-chips">
                {(features.suggested_prompts || []).map((p) => (
                  <button key={p} type="button" className="chip" onClick={() => send(p)}>{p}</button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, i) => <ChatMessageBubble key={m.id || i} message={m} />)
          )}
          {loading ? <div className="chat-msg bot">思考中…</div> : null}
          <div ref={bottomRef} />
        </div>

        <footer className="chat-composer">
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept=".docx,.pdf,.xlsx,.xls,.txt"
            onChange={(e) => uploadFile(e.target.files?.[0])}
          />
          <button type="button" className="ghost" onClick={() => fileRef.current?.click()} disabled={loading} title="上传文件">
            📎
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && send()}
            placeholder="输入问题，例如：帮我新建一份标书 / 公司有哪些资质？"
            disabled={loading}
          />
          <button type="button" onClick={() => send()} disabled={loading || !input.trim()}>发送</button>
        </footer>
      </main>
    </div>
  )
}
