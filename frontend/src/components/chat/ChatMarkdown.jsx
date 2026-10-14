import React from 'react'
import { parseInline, parseMarkdown } from './chatTranscriptModel'

function Inline({ text, marker }) {
  return parseInline(text).map((part, index) => {
    const key = `${marker}-${index}`
    if (part.type === 'code') return <code key={key}>{part.text}</code>
    if (part.type === 'strong') return <strong key={key}>{part.text}</strong>
    if (part.type === 'link') {
      return (
        <a key={key} href={part.href} target="_blank" rel="noreferrer">
          {part.text}
        </a>
      )
    }
    return <span key={key}>{part.text}</span>
  })
}

function RichText({ text, marker }) {
  const lines = String(text || '').split('\n')
  return lines.map((line, index) => (
    <span key={`${marker}-l${index}`}>
      {index > 0 ? <br /> : null}
      <Inline text={line} marker={`${marker}-${index}`} />
    </span>
  ))
}

export default function ChatMarkdown({ text }) {
  const blocks = parseMarkdown(text)
  if (!blocks.length) return null
  return (
    <div className="chat-md">
      {blocks.map((block, index) => {
        const key = `b${index}`
        if (block.type === 'heading') {
          const Tag = `h${block.level}`
          return <Tag key={key}><Inline text={block.text} marker={key} /></Tag>
        }
        if (block.type === 'ul' || block.type === 'ol') {
          const Tag = block.type
          return (
            <Tag key={key}>
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-${itemIndex}`}>
                  <RichText text={item} marker={`${key}-${itemIndex}`} />
                </li>
              ))}
            </Tag>
          )
        }
        if (block.type === 'code') {
          return (
            <pre key={key}>
              {block.lang ? <span className="chat-md-lang">{block.lang}</span> : null}
              <code>{block.text}</code>
            </pre>
          )
        }
        return (
          <p key={key}>
            <RichText text={block.text} marker={key} />
          </p>
        )
      })}
    </div>
  )
}
