import React, { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api/client'
import ChatMessageBubble from '../components/chat/ChatMessageBubble'
import DocumentWorkspace from '../components/chat/DocumentWorkspace'
import { formatTime } from '../utils/format'

export default function ChatPage() {
  const { showToast } = useApp()
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [workspace, setWorkspace] = useState({})
  const [paragraphs, setParagraphs] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [features, setFeatures] = useState({ feature_cards: [], suggested_prompts: [] })
  const [renamingId, setRenamingId] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [selectedText, setSelectedText] = useState('')
  const [showSessions, setShowSessions] = useState(false)
  const fileRef = useRef(null)
  const bottomRef = useRef(null)

  const refreshWorkspace = async (id) => {
    if (!id) return
    const data = await api.getChatWorkspace(id)
    setWorkspace(data.workspace || {})
    setParagraphs(data.paragraphs || [])
  }

  const refreshSessions = async () => {
    const list = await api.listChatSessions()
    setSessions(list)
    return list
  }

  const loadSession = async (id) => {
    const data = await api.getChatSession(id)
    setSessionId(data.id)
    setMessages(data.messages || [])
    setWorkspace(data.workspace || {})
    await refreshWorkspace(id)
    setShowSessions(false)
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
      const res = await api.sendChatMessage(id, q, {
        selected_text: selectedText,
      })
      setMessages((m) => [
        ...m.filter((x) => x !== optimistic),
        res.user_message,
        res.assistant_message,
      ])
      if (res.session) {
        setSessions((list) => [res.session, ...list.filter((s) => s.id !== res.session.id)])
        setWorkspace(res.session.workspace || {})
      }
      if (res.metadata?.workspace_updated || res.session?.workspace) {
        await refreshWorkspace(id)
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
    setWorkspace({})
    setParagraphs([])
    await refreshSessions()
    setShowSessions(false)
  }

  const uploadFile = async (file) => {
    if (!file || loading) return
    setLoading(true)
    try {
      const id = await ensureSession()
      const res = await api.uploadChatFile(id, file)
      setMessages((m) => [...m, res.user_message, res.assistant_message])
      setWorkspace(res.workspace || {})
      await refreshWorkspace(id)
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

  const onParagraphEdit = async (paragraphIndex, text) => {
    if (!sessionId) return
    const res = await api.updateWorkspaceParagraph(sessionId, paragraphIndex, text)
    setWorkspace(res.workspace || {})
    setParagraphs(res.paragraphs || [])
    showToast('段落已保存')
  }

  return (
    <div className="chat-workspace-page">
      <header className="chat-workspace-topbar">
        <Link to="/" className="ghost">← 返回</Link>
        <strong>文档 Agent 工作区</strong>
        <div className="chat-workspace-top-actions">
          <button type="button" className="ghost" onClick={() => setShowSessions((v) => !v)}>对话列表</button>
          <button type="button" onClick={newChat}>新对话</button>
        </div>
      </header>

      {showSessions ? (
        <div className="chat-session-drawer">
          {sessions.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`chat-session-item ${sessionId === s.id ? 'active' : ''}`}
              onClick={() => loadSession(s.id)}
            >
              <strong>{s.title}</strong>
              <span>{formatTime(s.updated_at || s.created_at)}</span>
            </button>
          ))}
        </div>
      ) : null}

      <div className="chat-workspace-split">
        <section className="chat-workspace-doc">
          <DocumentWorkspace
            sessionId={sessionId}
            workspace={workspace}
            paragraphs={paragraphs}
            selectedText={selectedText}
            onSelectText={setSelectedText}
            onParagraphEdit={onParagraphEdit}
            onRefresh={() => refreshWorkspace(sessionId)}
            onlyOfficeEnabled={!!features.onlyoffice?.enabled}
          />
        </section>

        <aside className="chat-workspace-panel">
          <div className="chat-panel-head">
            <h3>Agent 对话</h3>
            <p className="muted">上传模板 + 编写要求 → 生成标书；选中片段 → 多轮修改</p>
          </div>

          <div className="chat-messages-area compact">
            {messages.length === 0 && !loading ? (
              <div className="chat-empty compact">
                <div className="chat-prompt-chips">
                  {(features.suggested_prompts || []).map((p) => (
                    <button key={p} type="button" className="chip" onClick={() => send(p)}>{p}</button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((m, i) => <ChatMessageBubble key={m.id || i} message={m} />)
            )}
            {loading ? <div className="chat-msg bot">处理中…</div> : null}
            <div ref={bottomRef} />
          </div>

          {selectedText ? (
            <div className="chat-selection-hint">
              将修改选中文本：
              <em>{selectedText.slice(0, 60)}{selectedText.length > 60 ? '…' : ''}</em>
              <button type="button" className="ghost tiny" onClick={() => setSelectedText('')}>清除</button>
            </div>
          ) : null}

          <footer className="chat-composer compact">
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept=".docx"
              onChange={(e) => uploadFile(e.target.files?.[0])}
            />
            <button type="button" className="ghost" onClick={() => fileRef.current?.click()} disabled={loading} title="上传模板 DOCX">📎</button>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && send()}
              placeholder="编写要求 / 修改指令…"
              disabled={loading}
            />
            <button type="button" onClick={() => send()} disabled={loading || !input.trim()}>发送</button>
          </footer>
        </aside>
      </div>
    </div>
  )
}
