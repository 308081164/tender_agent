import React, { useState } from 'react'
import ChatActionCards from './ChatActionCards'
import ChatAttachmentChip from './ChatAttachmentChip'
import ChatMarkdown from './ChatMarkdown'
import ChatCards from './cards'
import { resolveUserTurn, sourceCards, visibleProvenance } from './chatTranscriptModel'

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.left = '-9999px'
    document.body.appendChild(area)
    area.select()
    try {
      return document.execCommand('copy')
    } finally {
      area.remove()
    }
  }
}

function SourceList({ sources }) {
  const cards = sourceCards(sources)
  if (!cards.length) return null
  return (
    <div className="chat-source-list">
      {cards.map((card) => (
        <a key={card.url} className="chat-source-card" href={card.url} target="_blank" rel="noreferrer">
          <span className="chat-source-title">{card.title}</span>
          {card.domain && card.domain !== card.title ? (
            <span className="chat-source-domain">{card.domain}</span>
          ) : null}
        </a>
      ))}
    </div>
  )
}

export default function ChatMessageBubble({ message, onCardAction, actingCardId, streaming = false }) {
  const [copied, setCopied] = useState(false)
  const isUser = message.role === 'user'
  const actions = message.metadata?.actions || []
  const cards = message.metadata?.cards || []
  const content = message.content || ''

  const copy = async () => {
    const ok = await copyText(content)
    if (!ok) return
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1200)
  }

  if (isUser) {
    const turn = resolveUserTurn(message)
    if (!turn.text && !turn.chips.length) return null
    return (
      <article className="chat-turn user">
        {turn.chips.length ? (
          <div className="chat-user-chips">
            {turn.chips.map((chip, index) => (
              <ChatAttachmentChip key={`${chip.kind}-${chip.name}-${index}`} item={chip} />
            ))}
          </div>
        ) : null}
        {turn.text ? <div className="chat-user-bubble">{turn.text}</div> : null}
      </article>
    )
  }

  const provenance = visibleProvenance(message.source)
  const showBody = Boolean(content) || streaming

  return (
    <article className={`chat-turn assistant${streaming ? ' is-streaming' : ''}`}>
      <div className="chat-reading">
        {content ? <ChatMarkdown text={content} /> : null}
        {streaming && !content ? <div className="chat-inline-status" role="status">思考中</div> : null}
        {!streaming || content ? <SourceList sources={message.metadata?.sources} /> : null}
        {provenance ? <div className="chat-msg-source">来源：{provenance}</div> : null}
        <ChatCards
          cards={cards}
          message={message}
          onAction={onCardAction}
          actingCardId={actingCardId}
        />
        <ChatActionCards actions={actions} />
      </div>
      {showBody && content ? (
        <div className="chat-turn-actions">
          <button type="button" className="chat-copy" onClick={copy}>
            {copied ? '已复制' : '复制'}
          </button>
        </div>
      ) : null}
    </article>
  )
}
