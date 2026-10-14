import React from 'react'
import ChatMessageBubble from './ChatMessageBubble'

export default function ChatTranscript({
  messages,
  loading = false,
  streaming = false,
  onCardAction,
  actingCardId,
  empty = null,
}) {
  const last = messages[messages.length - 1]
  const waitingInAssistant = Boolean(loading && streaming && last?.role === 'assistant')
  const showStatus = Boolean(loading && !waitingInAssistant)

  return (
    <div className="chat-transcript">
      {messages.length === 0 && !loading ? empty : null}
      {messages.map((message, index) => (
        <ChatMessageBubble
          key={message.id || index}
          message={message}
          onCardAction={onCardAction}
          actingCardId={actingCardId}
          streaming={waitingInAssistant && index === messages.length - 1}
        />
      ))}
      {showStatus ? <div className="chat-inline-status" role="status">思考中</div> : null}
    </div>
  )
}
