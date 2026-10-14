/** 日志查看弹窗的周期筛选。时间戳行自成一条，后续无时间戳的行跟着它。 */

const SECTION_RE = /^===== .+ =====$/
const FULL_BODY = '(\\d{4})-(\\d{2})-(\\d{2})[ T](\\d{2}):(\\d{2}):(\\d{2})(?:[.,](\\d{1,6}))?(?:\\s*(Z|UTC|GMT|CST|[+-]\\d{2}(?::?\\d{2})?))?(?!\\w)'
const FULL_RE = new RegExp(`^[ ]{0,2}${FULL_BODY}`, 'i')
const FULL_SEARCH_RE = new RegExp(FULL_BODY, 'i')
const TIME_RE = /^[ ]{0,2}\[(\d{1,2})[:：](\d{2})[:：](\d{2})(?:[.,](\d{1,6}))?\]/
const BANNER_RE = /^\s*---\s.*---\s*$/
const HOUR_MS = 60 * 60 * 1000
const DAY_MS = 24 * HOUR_MS

export const LOG_RANGE_PRESETS = [
  { id: 'all', label: '全部' },
  { id: 'hour', label: '最近 1 小时' },
  { id: 'today', label: '今天' },
  { id: 'week', label: '近 7 天' },
  { id: 'custom', label: '自定义' },
]

function millisFromFraction(frac) {
  if (!frac) return 0
  return Number(frac.slice(0, 3).padEnd(3, '0'))
}

function offsetMinutes(token) {
  if (!token) return null
  const upper = token.toUpperCase()
  if (upper === 'Z' || upper === 'UTC' || upper === 'GMT') return 0
  // 本机 PostgreSQL 在中国时区把 Asia/Shanghai 印成 CST。
  if (upper === 'CST') return 8 * 60
  const match = /^([+-])(\d{2})(?::?(\d{2}))?$/.exec(token)
  if (!match) return null
  const sign = match[1] === '-' ? -1 : 1
  return sign * (Number(match[2]) * 60 + Number(match[3] || 0))
}

function validCalendarDate(year, month, day) {
  const date = new Date(year, month - 1, day)
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day
}

function timestampMs(year, month, day, hour, minute, second, millis, offsetMin) {
  if (
    !validCalendarDate(year, month, day)
    || hour > 23 || minute > 59 || second > 59
  ) return null
  if (offsetMin == null) {
    return new Date(year, month - 1, day, hour, minute, second, millis).getTime()
  }
  return Date.UTC(year, month - 1, day, hour, minute, second, millis) - offsetMin * 60 * 1000
}

function localParts(ms) {
  const date = new Date(ms)
  return {
    y: date.getFullYear(),
    m: date.getMonth() + 1,
    d: date.getDate(),
    minutes: date.getHours() * 60 + date.getMinutes(),
  }
}

function shiftDate(year, month, day, days) {
  const date = new Date(year, month - 1, day + days)
  return { y: date.getFullYear(), m: date.getMonth() + 1, d: date.getDate() }
}

function fromFullMatch(match) {
  const millis = millisFromFraction(match[7])
  const offsetMin = offsetMinutes(match[8])
  const ms = timestampMs(
    Number(match[1]),
    Number(match[2]),
    Number(match[3]),
    Number(match[4]),
    Number(match[5]),
    Number(match[6]),
    millis,
    offsetMin,
  )
  if (ms == null) return null
  return { ms, local: localParts(ms) }
}

function remember(context, local) {
  context.y = local.y
  context.m = local.m
  context.d = local.d
  context.lastMinutes = local.minutes
}

/**
 * 解析一行日志的时间。无日期的 [HH:MM:SS] 沿用本段最近一次完整日期；
 * 时钟明显回绕时顺延到下一天。返回 null 表示这行是续行。
 */
export function parseLogLineTimestamp(line, context) {
  if (!line || SECTION_RE.test(line)) return null
  const leading = FULL_RE.exec(line)
  if (leading) {
    const parsed = fromFullMatch(leading)
    if (!parsed) return null
    remember(context, parsed.local)
    return parsed.ms
  }
  if (BANNER_RE.test(line)) {
    const found = FULL_SEARCH_RE.exec(line)
    if (!found) return null
    const parsed = fromFullMatch(found)
    if (!parsed) return null
    remember(context, parsed.local)
    return parsed.ms
  }
  const clock = TIME_RE.exec(line)
  if (!clock || context.y == null) return null
  let { y, m, d } = context
  const hour = Number(clock[1])
  const minute = Number(clock[2])
  const second = Number(clock[3])
  if (hour > 23 || minute > 59 || second > 59) return null
  const minutes = hour * 60 + minute
  if (context.lastMinutes != null && minutes + 60 < context.lastMinutes) {
    const next = shiftDate(y, m, d, 1)
    y = next.y
    m = next.m
    d = next.d
  }
  const ms = timestampMs(y, m, d, hour, minute, second, millisFromFraction(clock[4]), null)
  if (ms == null) return null
  remember(context, { y, m, d, minutes })
  return ms
}

function groupEntries(lines) {
  const entries = []
  let current = null
  const context = { y: null, m: null, d: null, lastMinutes: null }
  for (const line of lines) {
    const ts = parseLogLineTimestamp(line, context)
    if (ts != null) {
      current = { ts, lines: [line] }
      entries.push(current)
    } else if (current) {
      current.lines.push(line)
    } else {
      current = { ts: null, lines: [line] }
      entries.push(current)
    }
  }
  return entries
}

function splitSections(lines) {
  const sections = []
  let header = null
  let body = []
  const flush = () => {
    if (header !== null || body.length) sections.push({ header, body })
    body = []
  }
  for (const line of lines) {
    if (SECTION_RE.test(line)) {
      flush()
      header = line
      body = []
    } else {
      body.push(line)
    }
  }
  flush()
  return sections
}

export function presetRange(preset, now = new Date()) {
  const current = now instanceof Date ? now : new Date(now)
  if (preset === 'hour') {
    const endMs = current.getTime()
    return { startMs: endMs - HOUR_MS, endMs }
  }
  if (preset === 'today') {
    const start = new Date(current.getFullYear(), current.getMonth(), current.getDate())
    return { startMs: start.getTime(), endMs: start.getTime() + DAY_MS - 1 }
  }
  if (preset === 'week') {
    const start = new Date(current.getFullYear(), current.getMonth(), current.getDate() - 6)
    const today = new Date(current.getFullYear(), current.getMonth(), current.getDate())
    return { startMs: start.getTime(), endMs: today.getTime() + DAY_MS - 1 }
  }
  return null
}

export function customRange(startValue, endValue) {
  if (!startValue || !endValue) return { ok: false, reason: 'incomplete' }
  const startMs = dateTimeLocalMs(startValue, 'start')
  const endMs = dateTimeLocalMs(endValue, 'end')
  if (startMs == null || endMs == null) return { ok: false, reason: 'invalid' }
  if (startMs > endMs) return { ok: false, reason: 'order' }
  return { ok: true, range: { startMs, endMs } }
}

function dateTimeLocalMs(value, bound) {
  const match = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(String(value).trim())
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const hour = Number(match[4])
  const minute = Number(match[5])
  const hasSeconds = match[6] !== undefined
  const second = hasSeconds ? Number(match[6]) : (bound === 'end' ? 59 : 0)
  const millis = !hasSeconds && bound === 'end' ? 999 : (bound === 'end' ? 999 : 0)
  return timestampMs(year, month, day, hour, minute, second, millis, null)
}

export function filterLogLines(lines, range) {
  if (!range) return lines.slice()
  const visible = []
  for (const section of splitSections(lines)) {
    const kept = []
    for (const entry of groupEntries(section.body)) {
      if (entry.ts == null) continue
      if (entry.ts >= range.startMs && entry.ts <= range.endMs) kept.push(...entry.lines)
    }
    if (!kept.length) continue
    if (section.header) visible.push(section.header)
    visible.push(...kept)
  }
  return visible
}

export function isLogSectionHeader(line) {
  return SECTION_RE.test(line)
}
