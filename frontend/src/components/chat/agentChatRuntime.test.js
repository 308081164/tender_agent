import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import { buildAnchorPayload, keepStreamedReply, mentionQueryAt, stripMentionQuery } from './agentChatRuntime.js'

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

test('chat surfaces keep streaming, web search, and attachment chips', () => {
  const root = new URL('../../', import.meta.url)
  const read = (name) => fs.readFileSync(new URL(name, root), 'utf8')
  const chatPage = read('pages/ChatPage.jsx')
  const workspace = read('pages/ProjectWorkspacePage.jsx')
  const drawer = read('components/ChatDrawer.jsx')
  const composer = read('components/chat/ChatComposer.jsx')
  assert.match(chatPage, /sendChatMessageStream/)
  assert.match(chatPage, /keepStreamedReply/)
  assert.doesNotMatch(chatPage, /api\.sendChatMessage\(/)
  assert.match(workspace, /sendChatMessageStream/)
  assert.match(workspace, /keepStreamedReply/)
  assert.match(drawer, /mentionItems/)
  assert.match(composer, /联网/)
  assert.match(composer, /composer-attach-row/)
  assert.match(composer, /mention-menu/)
  assert.match(read('components/chat/ChatTranscript.jsx'), /chat-reading|ChatMessageBubble/)
})
