import React from 'react'
import ChatDrawer from './ChatDrawer'

export default function FloatingChat({ chat }) {
  return (
    <>
      {!chat.open && (
        <button
          type="button"
          className="floating-chat-btn"
          onClick={chat.openDrawer}
          aria-label="打开 AI 助手"
        >
          <span className="floating-chat-icon">AI</span>
          <span className="floating-chat-label">AI 助手</span>
        </button>
      )}
      <ChatDrawer
        open={chat.open}
        onClose={chat.closeDrawer}
        sessions={chat.sessions}
        sessionId={chat.sessionId}
        messages={chat.messages}
        chatInput={chat.chatInput}
        setChatInput={chat.setChatInput}
        askChat={chat.askChat}
        loading={chat.loading}
        showHistory={chat.showHistory}
        setShowHistory={chat.setShowHistory}
        onNewChat={chat.newChat}
        onSelectSession={chat.loadSession}
      />
    </>
  )
}
