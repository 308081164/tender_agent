import React from 'react'

export function highlightText(text, fields) {
  if (!text) return text
  let result = text
  const values = Object.values(fields || {}).filter(Boolean).map(String).sort((a, b) => b.length - a.length)
  for (const v of values) {
    if (v.length < 2) continue
    result = result.split(v).join(`⟦${v}⟧`)
  }
  return result.split(/⟦|⟧/).map((part, i) =>
    i % 2 === 1 ? <mark className="highlight" key={i}>{part}</mark> : <span key={i}>{part}</span>
  )
}
