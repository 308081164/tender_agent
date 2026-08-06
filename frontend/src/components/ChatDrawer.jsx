import React from 'react'
import { formatTime } from '../utils/format'

export default function ChatDrawer({
  open,
  onClose,
  sessions,
  sessionId,
  messages,
  chatInput,
  setChatInput,
  askChat,
  loading,
  showHistory,
  setShowHistory,
  onNewChat,
  onSelectSession,
}) {
  if (!open) return null

  return (
    <div className="chat-drawer-root">
      <div className="chat-drawer-mask" onClick={onClose} />
      <aside className="chat-drawer" role="dialog" aria-label="企业问答">
        <header className="chat-drawer-head">
          <div>
            <div className="wizard-kicker">企业问答</div>
            <h3>智能助手</h3>
          </div>
          <div className="chat-drawer-tools">
            <button type="button" className="ghost" onClick={onNewChat} disabled={loading}>
              New Chat
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => setShowHistory((v) => !v)}
            >
              {showHistory ? '返回对话' : '历史'}
            </button>
            <button type="button" className="ghost" onClick={onClose} aria-label="关闭">
              ×
            </button>
          </div>
        </header>

        {showHistory ? (
          <div className="chat-history-list">
            {sessions.length === 0 && <div className="empty">暂无历史对话</div>}
            {sessions.map((s) => (
              <button
                type="button"
                key={s.id}
                className={`chat-history-item ${sessionId === s.id ? 'active' : ''}`}
                onClick={() => onSelectSession(s.id)}
              >
                <strong>{s.title || `会话 #${s.id}`}</strong>
                <span>{formatTime(s.updated_at || s.created_at)}</span>
              </button>
            ))}
          </div>
        ) : (
          <>
            <div className="chat-drawer-messages">
              {messages.length === 0 && (
                <div className="msg bot">
                  你好，我是企业问答助手。可询问资质、业绩、人员等问题。支持多轮上下文。
                </div>
              )}
              {messages.map((m, i) => (
                <div
                  className={`msg ${m.role === 'user' ? 'user' : 'bot'}`}
                  key={m.id || i}
                >
                  {m.content || m.text}
                  {m.source ? <span className="src">来源：{m.source}</span> : null}
                </div>
              ))}
              {loading && <div className="msg bot">思考中…</div>}
            </div>
            <div className="chat-drawer-input">
              <input
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && askChat()}
                placeholder="例如：是否具备铁路总承包一级资质？"
                disabled={loading}
              />
              <button onClick={askChat} disabled={loading || !chatInput.trim()}>
                发送
              </button>
            </div>
          </>
        )}
      </aside>
    </div>
  )
}
