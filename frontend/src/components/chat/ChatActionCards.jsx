import React from 'react'
import { Link } from 'react-router-dom'

export default function ChatActionCards({ actions = [] }) {
  if (!actions?.length) return null
  return (
    <div className="chat-action-cards">
      {actions.map((action, i) => (
        <Link
          key={`${action.url}-${i}`}
          to={action.url}
          className={`chat-action-card ${action.primary ? 'primary' : ''}`}
        >
          {action.label}
        </Link>
      ))}
    </div>
  )
}
