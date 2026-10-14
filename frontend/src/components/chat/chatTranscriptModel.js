const EXT_TYPES = {
  pdf: 'PDF',
  doc: 'DOC',
  docx: 'DOCX',
  txt: 'TXT',
  png: 'PNG',
  jpg: 'JPG',
  jpeg: 'JPG',
  webp: 'WEBP',
  gif: 'GIF',
  zip: 'ZIP',
  tif: 'TIFF',
  tiff: 'TIFF',
  bmp: 'BMP',
}

const MACHINE_SOURCES = new Set(['ai', 'kb', 'faq', 'rules', 'system', 'template', 'meta', 'fallback'])

export function typeLabel(name, kind = 'file') {
  if (kind === 'folder') return '文件夹'
  const base = String(name || '').split(/[/\\]/).pop() || ''
  const ext = base.includes('.') ? base.split('.').pop().toLowerCase() : ''
  if (!ext) return '文件'
  return EXT_TYPES[ext] || ext.toUpperCase().slice(0, 6)
}

export function isSafeHref(url) {
  const value = String(url || '').trim()
  if (!value) return false
  if (value.startsWith('/') && !value.startsWith('//')) return true
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

export function normalizeChip(raw) {
  if (!raw || typeof raw !== 'object') return null
  const name = String(raw.name || raw.filename || '').trim()
  if (!name) return null
  const kind = raw.kind === 'folder' ? 'folder' : 'file'
  const type = String(raw.type || '').trim() || typeLabel(name, kind)
  return { name, kind, type }
}

function folderChipFromPath(label, pathValue) {
  const path = String(pathValue || '').trim()
  const looksPath = /^([A-Za-z]:[\\/]|\/|\\\\)/.test(path)
  const folderLabel = /文件夹|目录/.test(label || '')
  if (!path || (!looksPath && !folderLabel)) return null
  if (!folderLabel && !looksPath) return null
  if (!folderLabel) return null
  const name = path.split(/[/\\]/).filter(Boolean).pop() || label || '文件夹'
  return { name, kind: 'folder', type: '文件夹' }
}

/** 历史消息把路径写进正文时，转成芯片并不再展示那段原文。 */
export function parseLegacyAttachmentContent(content) {
  const text = String(content || '').trim()
  if (!text) return { chips: [], hideText: false }

  let match = text.match(/^\[上传文件\]\s*(.+)$/)
  if (match) {
    const chip = normalizeChip({ name: match[1].trim(), kind: 'file' })
    return { chips: chip ? [chip] : [], hideText: Boolean(chip) }
  }

  match = text.match(/^\[上传\s*\d+\s*个文件\]\s*(.*)$/)
  if (match) {
    const names = match[1].replace(/…$/, '').split('、').map((part) => part.trim()).filter(Boolean)
    const chips = names.map((name) => normalizeChip({ name, kind: 'file' })).filter(Boolean)
    return { chips, hideText: chips.length > 0 }
  }

  match = text.match(/^\[([^\]]+)\]\s+(\S[\s\S]*)$/)
  if (match) {
    const chip = folderChipFromPath(match[1].trim(), match[2].trim())
    if (chip) return { chips: [chip], hideText: true }
  }

  return { chips: [], hideText: false }
}

export function resolveUserTurn(message) {
  const content = String(message?.content || '')
  const meta = message?.metadata || {}
  let chips = []
  if (Array.isArray(meta.attachments) && meta.attachments.length) {
    chips = meta.attachments.map(normalizeChip).filter(Boolean)
  } else if (meta.attachment?.filename) {
    const chip = normalizeChip({ name: meta.attachment.filename, kind: 'file' })
    if (chip) chips = [chip]
  }
  if (Array.isArray(meta.mentions) && meta.mentions.length) {
    const mentioned = meta.mentions.map((item) => normalizeChip({
      name: item.label || item.name,
      kind: 'file',
      type: item.kind === 'section' ? '章节' : '文件',
    })).filter(Boolean)
    chips = [...chips, ...mentioned]
  }
  const legacy = parseLegacyAttachmentContent(content)
  if (!chips.length) chips = legacy.chips
  const text = legacy.hideText ? '' : content
  return { text, chips }
}

export function sourceCards(sources) {
  if (!Array.isArray(sources)) return []
  const seen = new Set()
  const cards = []
  for (const item of sources) {
    if (!item || typeof item !== 'object') continue
    const url = String(item.url || '').trim()
    if (!isSafeHref(url) || url.startsWith('/') || seen.has(url)) continue
    seen.add(url)
    let domain = ''
    try {
      domain = new URL(url).hostname.replace(/^www\./, '')
    } catch {
      domain = ''
    }
    const title = String(item.title || '').trim() || domain || url
    cards.push({ url, title, domain })
  }
  return cards
}

export function visibleProvenance(source) {
  const value = String(source || '').trim()
  if (!value || MACHINE_SOURCES.has(value.toLowerCase())) return ''
  return value
}

export function chipPayload(items) {
  return (items || []).map((item) => {
    const name = String(item?.name || '').trim()
    const kind = item?.kind === 'folder' ? 'folder' : 'file'
    return {
      name,
      kind,
      type: item?.type || typeLabel(name, kind),
    }
  }).filter((item) => item.name)
}

export function parseInline(text) {
  const source = String(text || '')
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)\s]+\))|(https?:\/\/[^\s<]+)/g
  const parts = []
  let last = 0
  let match = re.exec(source)
  while (match) {
    if (match.index > last) parts.push({ type: 'text', text: source.slice(last, match.index) })
    const token = match[0]
    if (token.startsWith('`')) {
      parts.push({ type: 'code', text: token.slice(1, -1) })
    } else if (token.startsWith('**')) {
      parts.push({ type: 'strong', text: token.slice(2, -2) })
    } else if (token.startsWith('[')) {
      const linked = token.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/)
      if (linked && isSafeHref(linked[2])) {
        parts.push({ type: 'link', text: linked[1], href: linked[2] })
      } else {
        parts.push({ type: 'text', text: token })
      }
    } else if (isSafeHref(token)) {
      parts.push({ type: 'link', text: token, href: token })
    } else {
      parts.push({ type: 'text', text: token })
    }
    last = match.index + token.length
    match = re.exec(source)
  }
  if (last < source.length) parts.push({ type: 'text', text: source.slice(last) })
  return parts
}

export function parseMarkdown(source) {
  const lines = String(source || '').replace(/\r\n/g, '\n').split('\n')
  const blocks = []
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    const fence = line.match(/^```([\w-]*)\s*$/)
    if (fence) {
      const lang = fence[1] || ''
      const buf = []
      index += 1
      while (index < lines.length && !/^```/.test(lines[index])) {
        buf.push(lines[index])
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push({ type: 'code', lang, text: buf.join('\n') })
      continue
    }
    if (!line.trim()) {
      index += 1
      continue
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2].trim() })
      index += 1
      continue
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items = []
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ''))
        index += 1
      }
      blocks.push({ type: 'ul', items })
      continue
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items = []
      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+[.)]\s+/, ''))
        index += 1
      }
      blocks.push({ type: 'ol', items })
      continue
    }
    const para = [line]
    index += 1
    while (
      index < lines.length
      && lines[index].trim()
      && !/^(#{1,3}\s|```|\s*[-*]\s+|\s*\d+[.)]\s+)/.test(lines[index])
    ) {
      para.push(lines[index])
      index += 1
    }
    blocks.push({ type: 'p', text: para.join('\n') })
  }
  return blocks
}
