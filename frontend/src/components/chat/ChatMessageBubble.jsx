import React from 'react'
import ChatActionCards from './ChatActionCards'

export default function ChatMessageBubble({ message }) {
  const isUser = message.role === 'user'
  const actions = message.metadata?.actions || []

  return (
    <div className={`chat-msg ${isUser ? 'user' : 'bot'}`}>
      <div className="chat-msg-content">{message.content}</div>
      {!isUser && message.source ? (
        <div className="chat-msg-source">来源：{message.source}</div>
      ) : null}
      {!isUser ? <ChatActionCards actions={actions} /> : null}
    </div>
  )
}
