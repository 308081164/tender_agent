import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  applyOnlyOfficeHighlights,
  bindOnlyOfficeSelection,
  buildAnchorPayload,
  keepStreamedReply,
  mentionQueryAt,
  onlyOfficeAnchorFromCommand,
  onlyOfficeHighlightCommand,
  onlyOfficeSelectionCommand,
  stripMentionQuery,
} from './agentChatRuntime.js'

function runInEditor(fn, Api, Asc) {
  const runner = new Function('Api', 'Asc', `return (${fn.toString()})()`)
  return runner(Api, Asc)
}

test('stream failure keeps partial text and the reason', () => {
  const kept = keepStreamedReply('已经写出一半', '模型连接中断')
  assert.match(kept, /已经写出一半/)
  assert.match(kept, /模型连接中断/)
  assert.match(keepStreamedReply('', '上游断开'), /上游断开/)
})

test('at-mention query and anchor payload do not invent paragraph 0', () => {
  const active = mentionQueryAt('请看 @技术', 6)
  assert.equal(active.query, '技术')
  assert.equal(stripMentionQuery('请看 @技术', active), '请看 ')
  assert.deepEqual(buildAnchorPayload(null), {})
  assert.deepEqual(buildAnchorPayload({}), {})
  assert.equal(buildAnchorPayload({ paragraph_index: 0 }).paragraph_index, 0)
  assert.equal(buildAnchorPayload({ block_id: 'section:3' }).block_id, 'section:3')
  assert.equal('paragraph_index' in buildAnchorPayload({ selected_text: '工期' }), false)
})

test('onlyoffice selection uses document position and real connector events', () => {
  const runtime = readFileSync(new URL('./agentChatRuntime.js', import.meta.url), 'utf8')
  const editor = readFileSync(new URL('./OnlyOfficeEditor.jsx', import.meta.url), 'utf8')
  assert.equal(runtime.includes('onSelectionChanged'), false)
  assert.equal(editor.includes('onSelectionChanged'), false)
  assert.equal(runtime.includes('globalThis.Api'), false)
  assert.equal(editor.includes('globalThis.Api'), false)

  const cover = { GetText() { return '封面' }, GetPosInParent() { return 0 } }
  const body = { GetText() { return '工期90天' }, GetPosInParent() { return 1 } }
  const current = { GetText() { return '工期90天' }, GetPosInParent() { return 1 } }
  assert.notEqual(current, body)
  const Api = {
    GetDocument() {
      return {
        GetRangeBySelect() {
          return {
            GetText() { return '工期90天' },
            GetParagraph() { return current },
          }
        },
        GetAllParagraphs() { return [cover, body] },
        GetCurrentParagraph() { return current },
      }
    },
  }
  const anchor = onlyOfficeAnchorFromCommand(runInEditor(onlyOfficeSelectionCommand, Api))
  assert.equal(anchor.selected_text, '工期90天')
  assert.equal(anchor.paragraph_index, 1)
  assert.equal(anchor.block_id, 'p:1')

  const seen = []
  const received = []
  bindOnlyOfficeSelection({
    attachEvent(name) { seen.push(name) },
    callCommand(fn, cb) { cb(runInEditor(fn, Api)) },
  }, (next) => received.push(next))
  assert.deepEqual(seen, ['onTargetPositionChanged', 'onClick'])
  assert.equal(seen.includes('onSelectionChanged'), false)
  assert.equal(received[0].paragraph_index, 1)
  assert.equal(received[0].block_id, 'p:1')

  const highlighted = []
  const paintApi = {
    GetDocument() {
      return {
        Search(text) {
          return [{ text, SetHighlight(color) { highlighted.push({ text, color }) } }]
        },
      }
    },
  }
  const painted = applyOnlyOfficeHighlights({
    callCommand(fn, cb) {
      return cb(runInEditor(fn, paintApi, { scope: { texts: ['90天'] } }))
    },
  }, ['90天'])
  assert.equal(painted, 1)
  assert.deepEqual(highlighted, [{ text: '90天', color: 'yellow' }])
  assert.equal(onlyOfficeHighlightCommand.toString().includes('globalThis.Api'), false)
})
