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

export const ONLYOFFICE_SELECTION_EVENTS = ['onTargetPositionChanged', 'onSelectionChanged']

export function onlyOfficeSelectionCommand() {
  var root = typeof globalThis !== 'undefined' ? globalThis : {}
  var api = root.Api || null
  if (!api || !api.GetDocument) return ''
  var doc = api.GetDocument()
  var selected = ''
  try {
    var range = doc.GetRangeBySelect && doc.GetRangeBySelect()
    if (range && range.GetText) selected = String(range.GetText() || '')
  } catch (err) {
    selected = ''
  }
  var index = -1
  var all = doc.GetAllParagraphs ? doc.GetAllParagraphs() : []
  var current = doc.GetCurrentParagraph ? doc.GetCurrentParagraph() : null
  for (var i = 0; i < all.length; i += 1) {
    if (current && all[i] === current) index = i
  }
  var blockId = index >= 0 ? `p:${index}` : ''
  if (!String(selected).trim() && index < 0) return ''
  return JSON.stringify({
    selected_text: String(selected || '').trim(),
    paragraph_index: index >= 0 ? index : null,
    block_id: blockId,
  })
}

export function onlyOfficeAnchorFromCommand(raw) {
  let data = raw
  if (typeof raw === 'string') {
    const text = raw.trim()
    if (!text) return null
    try { data = JSON.parse(text) } catch { return null }
  }
  if (!data || typeof data !== 'object') return null
  const selected = String(data.selected_text || data.text || '').trim()
  const blockId = String(data.block_id || '').trim()
  const hasIndex = data.paragraph_index !== undefined
    && data.paragraph_index !== null
    && data.paragraph_index !== ''
    && Number(data.paragraph_index) >= 0
  if (!selected && !blockId && !hasIndex) return null
  return {
    source: 'onlyoffice',
    ...(selected ? { selected_text: selected } : {}),
    ...(blockId ? { block_id: blockId } : {}),
    ...(hasIndex ? { paragraph_index: Number(data.paragraph_index) } : {}),
  }
}

export function readOnlyOfficeSelection(connector, onAnchor) {
  if (!connector || !onAnchor) return
  if (typeof connector.callCommand === 'function') {
    connector.callCommand(onlyOfficeSelectionCommand, (raw) => {
      const anchor = onlyOfficeAnchorFromCommand(raw)
      if (anchor) onAnchor(anchor)
    })
    return
  }
  connector.executeMethod?.('GetSelectedText', null, (text) => {
    const anchor = onlyOfficeAnchorFromCommand({ selected_text: text })
    if (anchor) onAnchor(anchor)
  })
}

export function onlyOfficeHighlightCommand() {
  var root = typeof globalThis !== 'undefined' ? globalThis : {}
  var scope = (root.Asc && root.Asc.scope) || {}
  var phrases = scope.texts || []
  var api = root.Api
  if (!api || !api.GetDocument) return 0
  var doc = api.GetDocument()
  if (!doc.Search) return 0
  var marked = 0
  for (var i = 0; i < phrases.length; i += 1) {
    var phrase = String(phrases[i] || '').trim()
    if (phrase.length < 2) continue
    var found = doc.Search(phrase) || []
    for (var j = 0; j < found.length; j += 1) {
      if (found[j] && found[j].SetHighlight) {
        found[j].SetHighlight('yellow')
        marked += 1
      }
    }
  }
  return marked
}

export function applyOnlyOfficeHighlights(connector, texts) {
  const phrases = (texts || []).map((item) => String(item || '').trim()).filter((item) => item.length >= 2).slice(0, 12)
  if (!connector || !phrases.length || typeof connector.callCommand !== 'function') return 0
  const root = typeof globalThis !== 'undefined' ? globalThis : {}
  root.Asc = root.Asc || {}
  root.Asc.scope = { ...(root.Asc.scope || {}), texts: phrases }
  return connector.callCommand(onlyOfficeHighlightCommand, (count) => count)
}

export function bindOnlyOfficeSelection(connector, onAnchor) {
  const pull = () => readOnlyOfficeSelection(connector, onAnchor)
  const bound = []
  if (connector?.attachEvent) {
    ONLYOFFICE_SELECTION_EVENTS.forEach((name) => {
      connector.attachEvent(name, pull)
      bound.push(name)
    })
  }
  pull()
  return bound
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
