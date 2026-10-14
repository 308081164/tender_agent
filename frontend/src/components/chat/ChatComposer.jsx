import React, { useEffect, useState } from 'react'
import { useAutoResizeTextarea } from '../../hooks/useAutoResizeTextarea'
import ChatAttachmentChip from './ChatAttachmentChip'
import { mentionChip, mentionQueryAt, stripMentionQuery } from './agentChatRuntime'

/**
 * Agent 对话输入：现代卡片式 Composer；Enter 发送，Shift+Enter 换行。
 */
export default function ChatComposer({
  value,
  onChange,
  onSend,
  loading = false,
  placeholder = '',
  compact = false,
  left = null,
  sendLabel = '发送',
  className = '',
  contextBar = null,
  loadingHint = null,
  innerPrefix = null,
  webSearch = false,
  onToggleWebSearch,
  attachments = [],
  onRemoveAttachment,
  mentions = [],
  onRemoveMention,
  mentionItems = [],
  onPickMention,
  onMentionQuery,
}) {
  const textareaRef = useAutoResizeTextarea(value, { minRows: 2, maxRows: 12 })
  const [mentionAt, setMentionAt] = useState(null)
  const canSend = !loading && (Boolean(value.trim()) || attachments.length > 0 || mentions.length > 0)
  const visibleMentions = mentionAt ? mentionItems : []

  useEffect(() => {
    onMentionQuery?.(mentionAt)
  }, [mentionAt, onMentionQuery])

  const syncMention = (nextValue, caret) => {
    const found = mentionQueryAt(nextValue, caret)
    setMentionAt(found)
  }

  const handleKeyDown = (e) => {
    if (mentionAt && e.key === 'Escape') {
      e.preventDefault()
      setMentionAt(null)
      return
    }
    if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return
    if (mentionAt && visibleMentions[0]) {
      e.preventDefault()
      pickMention(visibleMentions[0])
      return
    }
    e.preventDefault()
    if (canSend) onSend?.()
  }

  const pickMention = (item) => {
    const next = stripMentionQuery(value, mentionAt)
    setMentionAt(null)
    onChange?.(next)
    onPickMention?.(item)
  }

  return (
    <footer className={`chat-composer-shell${compact ? ' compact' : ''}${className ? ` ${className}` : ''}`}>
      {contextBar}
      <div className="composer-card">
        {loadingHint ? <div className="composer-loading-hint">{loadingHint}</div> : null}
        {innerPrefix}
        {attachments.length || mentions.length ? (
          <div className="composer-attach-row">
            {attachments.map((item) => (
              <ChatAttachmentChip
                key={item.id || `${item.kind}-${item.name}`}
                item={item}
                onRemove={loading ? undefined : () => onRemoveAttachment?.(item.id)}
              />
            ))}
            {mentions.map((item) => {
              const chip = mentionChip(item)
              if (!chip) return null
              return (
                <ChatAttachmentChip
                  key={`mention-${item.section_id || item.path || chip.name}`}
                  item={chip}
                  onRemove={loading ? undefined : () => onRemoveMention?.(item)}
                />
              )
            })}
          </div>
        ) : null}
        <div className="composer-input-wrap">
          {mentionAt ? (
            <div className="mention-menu" role="listbox" aria-label="引用文件或章节">
              {visibleMentions.length ? visibleMentions.map((item) => (
                <button
                  key={`${item.kind}-${item.section_id || item.path || item.label}`}
                  type="button"
                  className="mention-option"
                  onMouseDown={(e) => { e.preventDefault(); pickMention(item) }}
                >
                  <span className="attach-chip-type">{item.kind === 'section' ? '章节' : '文件'}</span>
                  <span>{item.label}</span>
                </button>
              )) : <div className="mention-empty muted">没有匹配的文件或章节</div>}
            </div>
          ) : null}
          <textarea
            ref={textareaRef}
            className="composer-card-input"
            rows={2}
            value={value}
            onChange={(e) => {
              onChange(e.target.value)
              syncMention(e.target.value, e.target.selectionStart)
            }}
            onKeyUp={(e) => syncMention(e.target.value, e.target.selectionStart)}
            onClick={(e) => syncMention(e.target.value, e.target.selectionStart)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={loading}
            aria-label="对话输入"
          />
        </div>
        <div className="composer-card-toolbar">
          <div className="composer-card-toolbar-left">
            <button
              type="button"
              className={`composer-web-toggle${webSearch ? ' on' : ''}`}
              aria-pressed={webSearch ? 'true' : 'false'}
              title="开启后，这条消息会联网检索公开资料，并在回复里附上标题和链接"
              disabled={loading}
              onClick={() => onToggleWebSearch?.(!webSearch)}
            >
              联网
            </button>
            {left}
          </div>
          <button
            type="button"
            className="composer-card-send"
            onClick={() => onSend?.()}
            disabled={!canSend}
          >
            {sendLabel}
          </button>
        </div>
      </div>
    </footer>
  )
}
