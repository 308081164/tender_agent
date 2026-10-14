/** 对话运行时里与界面无关的小函数，方便用 node:test 锁住验收行为。 */

export function keepStreamedReply(partial, errorMessage) {
  const why = String(errorMessage || '未知错误').trim() || '未知错误'
  const note = `（回复中断：${why}）`
  const text = String(partial || '')
  if (!text.trim()) return note
  if (text.includes(why)) return text
  return `${text.replace(/\s+$/, '')}\n\n${note}`
}

export function mentionQueryAt(value, caret) {
  const upto = String(value || '').slice(0, Number(caret) || 0)
  const match = upto.match(/(^|\s)@([^\s@]*)$/)
  if (!match) return null
  const query = match[2]
  return { query, start: upto.length - query.length - 1 }
}

export function stripMentionQuery(value, active) {
  if (!active) return value
  const end = active.start + 1 + String(active.query || '').length
  return `${String(value || '').slice(0, active.start)}${String(value || '').slice(end)}`
}

export function buildAnchorPayload(anchor) {
  if (!anchor || typeof anchor !== 'object') return {}
  const selected = String(anchor.selected_text || '').trim()
  const blockId = String(anchor.block_id || anchor.section_id || '').trim()
  const hasIndex = anchor.paragraph_index !== undefined
    && anchor.paragraph_index !== null
    && anchor.paragraph_index !== ''
    && !Number.isNaN(Number(anchor.paragraph_index))
  if (!selected && !blockId && !hasIndex) return {}
  const payload = {}
  if (selected) payload.selected_text = selected
  if (blockId) payload.block_id = blockId
  if (hasIndex) payload.paragraph_index = Number(anchor.paragraph_index)
  payload.anchor = {
    ...(selected ? { selected_text: selected } : {}),
    ...(blockId ? { block_id: blockId } : {}),
    ...(hasIndex ? { paragraph_index: Number(anchor.paragraph_index) } : {}),
  }
  return payload
}

export function appendStreamToken(message, token, event) {
  const tool = event?.tool
  if (tool?.tool) {
    const trace = [...(message.metadata?.tool_trace || []), { tool: tool.tool, ok: tool.ok !== false }]
    return { ...message, metadata: { ...(message.metadata || {}), tool_trace: trace } }
  }
  if (!token) return message
  return { ...message, content: `${message.content || ''}${token}` }
}

export function mentionChip(item) {
  if (!item) return null
  const name = String(item.label || item.name || '').trim()
  if (!name) return null
  const section = item.kind === 'section'
  return {
    name,
    kind: section ? 'section' : 'file',
    type: section ? '章节' : '文件',
  }
}
