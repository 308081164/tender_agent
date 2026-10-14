import assert from 'node:assert/strict'
import test from 'node:test'
import {
  applyOnlyOfficeHighlights,
  bindOnlyOfficeSelection,
  buildAnchorPayload,
  keepStreamedReply,
  mentionQueryAt,
  onlyOfficeAnchorFromCommand,
  onlyOfficeSelectionCommand,
  stripMentionQuery,
} from './agentChatRuntime.js'

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

test('onlyoffice selection command returns paragraph and block id', () => {
  const cover = { GetText() { return '封面' } }
  const body = { GetText() { return '工期90天' } }
  globalThis.Api = {
    GetDocument() {
      const paragraphs = [cover, body]
      return {
        GetRangeBySelect() { return { GetText() { return '工期90天' } } },
        GetAllParagraphs() { return paragraphs },
        GetCurrentParagraph() { return body },
      }
    },
  }
  const anchor = onlyOfficeAnchorFromCommand(onlyOfficeSelectionCommand())
  assert.equal(anchor.selected_text, '工期90天')
  assert.equal(anchor.paragraph_index, 1)
  assert.equal(anchor.block_id, 'p:1')
  const seen = []
  const connector = {
    attachEvent(name) { seen.push(name) },
    callCommand(fn, cb) { cb(fn()) },
  }
  const received = []
  bindOnlyOfficeSelection(connector, (next) => received.push(next))
  assert.deepEqual(seen, ['onTargetPositionChanged', 'onSelectionChanged'])
  assert.equal(received[0].paragraph_index, 1)
  const highlighted = []
  globalThis.Api.GetDocument = () => ({
    Search(text) { return [{ text, SetHighlight(color) { highlighted.push({ text, color }) } }] },
  })
  const painted = applyOnlyOfficeHighlights({
    callCommand(fn, cb) { return cb(fn()) },
  }, ['90天'])
  assert.equal(painted, 1)
  assert.deepEqual(highlighted, [{ text: '90天', color: 'yellow' }])
  delete globalThis.Api
  delete globalThis.Asc
})
