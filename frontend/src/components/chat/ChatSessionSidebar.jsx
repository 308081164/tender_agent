import React from 'react'
import { formatTime } from '../../utils/format'

export default function ChatSessionSidebar({
  open,
  onClose,
  sessions,
  sessionId,
  onSelectSession,
  onNewChat,
}) {
  return (
    <>
      <div
        className={`chat-history-overlay ${open ? 'open' : ''}`}
        onClick={onClose}
        aria-hidden={!open}
      />
      <aside className={`chat-history-sidebar ${open ? 'open' : ''}`} aria-label="历史对话">
        <header className="chat-history-sidebar-head">
          <strong>历史对话</strong>
          <button type="button" className="ghost icon-btn" onClick={onClose} aria-label="关闭">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </header>
        <div className="chat-history-sidebar-actions">
          <button type="button" onClick={onNewChat}>+ 新对话</button>
        </div>
        <div className="chat-history-sidebar-list">
          {sessions.length === 0 ? (
            <p className="muted chat-history-empty">暂无历史对话</p>
          ) : (
            sessions.map((s) => (
              <button
                key={s.id}
                type="button"
                className={`chat-session-item ${sessionId === s.id ? 'active' : ''}`}
                onClick={() => onSelectSession(s.id)}
              >
                <strong>{s.title || '新对话'}</strong>
                <span>{formatTime(s.updated_at || s.created_at)}</span>
              </button>
            ))
          )}
        </div>
      </aside>
    </>
  )
}
