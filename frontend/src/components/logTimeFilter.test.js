import assert from 'node:assert/strict'
import test from 'node:test'
import {
  customRange,
  filterLogLines,
  parseLogLineTimestamp,
  presetRange,
} from './logTimeFilter.js'

function context() {
  return { y: null, m: null, d: null, lastMinutes: null }
}

test('postgres CST timestamp is China Standard Time, continuation stays attached', () => {
  const lines = [
    '===== postgres.log =====',
    '2026-10-14 16:47:02.713 CST [1234] LOG:  database system is ready',
    '    DETAIL:  listening on 127.0.0.1',
    '2026-10-13 16:47:02.713 CST [1234] LOG:  yesterday',
  ]
  const hit = Date.UTC(2026, 9, 14, 8, 47, 2, 713)
  const ctx = context()
  assert.equal(parseLogLineTimestamp(lines[1], ctx), hit)
  assert.equal(parseLogLineTimestamp(lines[2], ctx), null)
  assert.deepEqual(filterLogLines(lines, { startMs: hit, endMs: hit }), [
    '===== postgres.log =====',
    lines[1],
    lines[2],
  ])
})

test('banner, python millis, and ISO timestamps parse', () => {
  const ctx = context()
  assert.equal(
    parseLogLineTimestamp('--- TenderAgent backend start 2026-10-14 16:40:00 port=18766 ---', ctx),
    new Date(2026, 9, 14, 16, 40, 0).getTime(),
  )
  assert.equal(
    parseLogLineTimestamp('2026-10-14 16:40:01,713 INFO app ready', ctx),
    new Date(2026, 9, 14, 16, 40, 1, 713).getTime(),
  )
  assert.equal(
    parseLogLineTimestamp('--- TenderAgent Electron 2026-10-14T08:47:02.713Z pid=3 ---', ctx),
    Date.UTC(2026, 9, 14, 8, 47, 2, 713),
  )
})

test('clock-only lines inherit the date and keep their own continuation', () => {
  const lines = [
    '===== launcher.log =====',
    '--- TenderAgent backend 2026-10-14 09:00:00 pid=1 ---',
    '[09:00:01] [launcher] boot',
    '  excluded port range',
    '[15:30:00] [launcher] still up',
    '===== backend.log =====',
    '--- TenderAgent backend start 2026-10-14 15:00:00 port=18766 ---',
    'INFO:     Started server process [9]',
  ]
  const start = new Date(2026, 9, 14, 15, 0, 0).getTime()
  const end = new Date(2026, 9, 14, 16, 0, 0).getTime()
  assert.deepEqual(filterLogLines(lines, { startMs: start, endMs: end }), [
    '===== launcher.log =====',
    '[15:30:00] [launcher] still up',
    '===== backend.log =====',
    '--- TenderAgent backend start 2026-10-14 15:00:00 port=18766 ---',
    'INFO:     Started server process [9]',
  ])
})

test('clock-only lines roll over midnight', () => {
  const lines = [
    '--- TenderAgent backend 2026-10-14 23:50:00 pid=1 ---',
    '[23:59:50] [launcher] late',
    '[00:01:00] [launcher] next day',
  ]
  const start = new Date(2026, 9, 15, 0, 0, 0).getTime()
  const end = new Date(2026, 9, 15, 0, 2, 0).getTime()
  assert.deepEqual(filterLogLines(lines, { startMs: start, endMs: end }), [
    '[00:01:00] [launcher] next day',
  ])
})

test('all preset keeps every line, including lines with no timestamp', () => {
  const lines = ['===== launcher.log =====', 'no timestamp here', '[12:00:00] later']
  assert.deepEqual(filterLogLines(lines, null), lines)
  assert.equal(presetRange('all', new Date(2026, 9, 14, 12)), null)
})

test('hour, today, and week windows are inclusive', () => {
  const now = new Date(2026, 9, 14, 16, 47, 2, 713)
  const hour = presetRange('hour', now)
  assert.equal(hour.endMs, now.getTime())
  assert.equal(hour.startMs, now.getTime() - 60 * 60 * 1000)
  const today = presetRange('today', now)
  assert.equal(today.startMs, new Date(2026, 9, 14).getTime())
  assert.equal(today.endMs, new Date(2026, 9, 14, 23, 59, 59, 999).getTime())
  const week = presetRange('week', now)
  assert.equal(week.startMs, new Date(2026, 9, 8).getTime())
  assert.equal(week.endMs, today.endMs)

  const lines = [
    `2026-10-14 16:47:02.713 edge`,
    `2026-10-14 15:47:02.713 hour-ago`,
    `2026-10-14 15:47:02.712 just-outside`,
  ]
  assert.deepEqual(filterLogLines(lines, hour), [lines[0], lines[1]])
})

test('custom range covers the whole minute and rejects a reversed span', () => {
  const ok = customRange('2026-10-14T16:47', '2026-10-14T16:47')
  assert.equal(ok.ok, true)
  const lines = [
    '2026-10-14 16:47:02.713 INFO inside',
    '    still inside',
    '2026-10-14 16:48:00.000 INFO outside',
  ]
  assert.deepEqual(filterLogLines(lines, ok.range), [lines[0], lines[1]])
  assert.deepEqual(customRange('', '2026-10-14T16:47'), { ok: false, reason: 'incomplete' })
  assert.equal(customRange('2026-10-14T18:00', '2026-10-14T16:47').reason, 'order')
})

test('a range with no hits returns no lines', () => {
  const lines = ['===== postgres.log =====', '2026-10-14 16:47:02.713 CST [1] LOG:  ready']
  assert.deepEqual(filterLogLines(lines, {
    startMs: Date.UTC(2020, 0, 1),
    endMs: Date.UTC(2020, 0, 2),
  }), [])
})
