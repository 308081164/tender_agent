import React from 'react'
import ChatActionCards from './ChatActionCards'
import ChatCards from './cards'

export default function ChatMessageBubble({ message, onCardAction, actingCardId }) {
  const isUser = message.role === 'user'
  const actions = message.metadata?.actions || []
  const cards = message.metadata?.cards || []

  return (
    <div className={`chat-msg ${isUser ? 'user' : 'bot'}`}>
      <div className="chat-msg-content">{message.content}</div>
      {!isUser && message.source ? (
        <div className="chat-msg-source">来源：{message.source}</div>
      ) : null}
      {!isUser ? (
        <ChatCards
          cards={cards}
          message={message}
          onAction={onCardAction}
          actingCardId={actingCardId}
        />
      ) : null}
      {!isUser ? <ChatActionCards actions={actions} /> : null}
    </div>
  )
}
