import React from 'react'
import { Link } from 'react-router-dom'

export default function ChatFeatureCards({ cards = [], onPrompt }) {
  if (!cards.length) return null
  return (
    <div className="chat-feature-grid">
      {cards.map((card) => (
        <Link key={card.id} to={card.url} className="chat-feature-card">
          <span className="chat-feature-icon">{card.icon}</span>
          <strong>{card.title}</strong>
          <p>{card.description}</p>
        </Link>
      ))}
      {onPrompt ? (
        <div className="chat-suggested-prompts">
          <div className="muted">试试问我：</div>
          <div className="chat-prompt-chips">
            {/* chips rendered by parent */}
          </div>
        </div>
      ) : null}
    </div>
  )
}
