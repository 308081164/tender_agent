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
  const location = String(anchor.location || '').trim()
  const hasIndex = anchor.paragraph_index !== undefined
    && anchor.paragraph_index !== null
    && anchor.paragraph_index !== ''
    && !Number.isNaN(Number(anchor.paragraph_index))
  const hasTable = anchor.table_index !== undefined
    && anchor.table_index !== null
    && anchor.row !== undefined
    && anchor.row !== null
    && anchor.col !== undefined
    && anchor.col !== null
  if (!selected && !blockId && !hasIndex && !location && !hasTable) return {}
  const payload = {}
  if (selected) payload.selected_text = selected
  if (blockId) payload.block_id = blockId
  if (hasIndex) payload.paragraph_index = Number(anchor.paragraph_index)
  if (location) payload.location = location
  if (hasTable) {
    payload.table_index = Number(anchor.table_index)
    payload.row = Number(anchor.row)
    payload.col = Number(anchor.col)
  }
  payload.anchor = {
    ...(selected ? { selected_text: selected } : {}),
    ...(blockId ? { block_id: blockId } : {}),
    ...(hasIndex ? { paragraph_index: Number(anchor.paragraph_index) } : {}),
    ...(location ? { location } : {}),
    ...(hasTable ? {
      table_index: Number(anchor.table_index),
      row: Number(anchor.row),
      col: Number(anchor.col),
    } : {}),
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

export const ONLYOFFICE_SELECTION_EVENTS = ['onTargetPositionChanged', 'onClick']

export function onlyOfficeSelectionCommand() {
  var doc = Api.GetDocument()
  var selected = ''
  var paragraph = null
  var range = null
  try {
    range = doc.GetRangeBySelect && doc.GetRangeBySelect()
    if (range && range.GetText) selected = String(range.GetText() || '')
    if (range && range.GetParagraph) paragraph = range.GetParagraph(0) || range.GetParagraph()
  } catch (err) {
    selected = ''
  }
  if (!paragraph && doc.GetCurrentParagraph) paragraph = doc.GetCurrentParagraph()
  var tableIndex = null
  var row = null
  var col = null
  var location = ''
  try {
    if (paragraph && paragraph.GetParentTableCell) {
      var cell = paragraph.GetParentTableCell()
      if (cell) {
        var table = paragraph.GetParentTable ? paragraph.GetParentTable() : null
        if (table && doc.GetAllTables) {
          var tables = doc.GetAllTables() || []
          for (var ti = 0; ti < tables.length; ti += 1) {
            if (tables[ti] === table) {
              tableIndex = ti
              break
            }
          }
        }
        var tableRow = cell.GetParentRow ? cell.GetParentRow() : null
        if (tableRow && cell.GetIndex) {
          row = tableRow.GetIndex ? tableRow.GetIndex() : null
          col = cell.GetIndex()
        }
      }
    }
  } catch (tableErr) {
    tableIndex = null
    row = null
    col = null
  }
  if (tableIndex !== null && row !== null && col !== null) {
    location = 'tbl:' + tableIndex + ':r' + row + ':c' + col
  }
  var index = -1
  if (paragraph && paragraph.GetPosInParent) {
    var pos = paragraph.GetPosInParent()
    var all = doc.GetAllParagraphs ? doc.GetAllParagraphs() : []
    var posKey = String(pos)
    var textKey = paragraph.GetText ? String(paragraph.GetText() || '') : ''
    for (var i = 0; i < all.length; i += 1) {
      var item = all[i]
      if (!item || !item.GetPosInParent) continue
      if (String(item.GetPosInParent()) !== posKey) continue
      var itemText = item.GetText ? String(item.GetText() || '') : ''
      if (itemText === textKey) {
        index = i
        break
      }
    }
  }
  if (!String(selected).trim() && index < 0 && !location) return ''
  var blockId = location || (index >= 0 ? ('p:' + index) : '')
  return JSON.stringify({
    selected_text: String(selected || '').trim(),
    paragraph_index: index >= 0 ? index : null,
    block_id: blockId,
    location: location || '',
    table_index: tableIndex,
    row: row,
    col: col,
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
  const location = String(data.location || '').trim()
  const hasIndex = data.paragraph_index !== undefined
    && data.paragraph_index !== null
    && data.paragraph_index !== ''
    && Number(data.paragraph_index) >= 0
  const hasTable = data.table_index !== undefined
    && data.table_index !== null
    && data.table_index !== ''
    && Number(data.table_index) >= 0
    && data.row !== undefined
    && data.row !== null
    && data.col !== undefined
    && data.col !== null
  if (!selected && !blockId && !hasIndex && !location && !hasTable) return null
  return {
    source: 'onlyoffice',
    ...(selected ? { selected_text: selected } : {}),
    ...(blockId ? { block_id: blockId } : {}),
    ...(hasIndex ? { paragraph_index: Number(data.paragraph_index) } : {}),
    ...(location ? { location } : {}),
    ...(hasTable ? {
      table_index: Number(data.table_index),
      row: Number(data.row),
      col: Number(data.col),
    } : {}),
  }
}

export function readOnlyOfficeSelection(connector, onAnchor) {
  if (!connector || !onAnchor) return
  if (typeof connector.callCommand !== 'function') return
  connector.callCommand(onlyOfficeSelectionCommand, (raw) => {
    onAnchor(onlyOfficeAnchorFromCommand(raw))
  })
}

export function onlyOfficeHighlightCommand() {
  var phrases = (typeof Asc !== 'undefined' && Asc.scope && Asc.scope.texts) || []
  var doc = Api.GetDocument()
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
