import assert from 'node:assert/strict'
import test from 'node:test'
import {
  chipPayload,
  parseLegacyAttachmentContent,
  parseMarkdown,
  resolveUserTurn,
  sourceCards,
  typeLabel,
} from './chatTranscriptModel.js'

test('type labels stay short', () => {
  assert.equal(typeLabel('招标文件.pdf'), 'PDF')
  assert.equal(typeLabel('资质包', 'folder'), '文件夹')
  assert.equal(typeLabel('notes'), '文件')
})

test('legacy upload text becomes chips and hides the dump', () => {
  const one = resolveUserTurn({ role: 'user', content: '[上传文件] 投标函.docx' })
  assert.equal(one.text, '')
  assert.deepEqual(one.chips, [{ name: '投标函.docx', kind: 'file', type: 'DOCX' }])

  const many = parseLegacyAttachmentContent('[上传 3 个文件] a.pdf、b.png、c.txt')
  assert.equal(many.hideText, true)
  assert.equal(many.chips.length, 3)
  assert.equal(many.chips[1].type, 'PNG')
})

test('folder paths are chips, ordinary bracket text is not', () => {
  const folder = resolveUserTurn({
    role: 'user',
    content: '[选择资质文件夹] /Users/me/资质包',
  })
  assert.equal(folder.text, '')
  assert.equal(folder.chips[0].name, '资质包')
  assert.equal(folder.chips[0].kind, 'folder')

  const note = resolveUserTurn({ role: 'user', content: '[注意] 请看 /tmp/a 这句说明' })
  assert.equal(note.text, '[注意] 请看 /tmp/a 这句说明')
  assert.equal(note.chips.length, 0)
})

test('metadata chips stay beside real user text', () => {
  const turn = resolveUserTurn({
    role: 'user',
    content: '帮我看一下报价',
    metadata: { attachments: [{ name: '报价.png', kind: 'file', type: 'PNG' }] },
  })
  assert.equal(turn.text, '帮我看一下报价')
  assert.equal(turn.chips[0].name, '报价.png')
})

test('historical single attachment object still renders', () => {
  const turn = resolveUserTurn({
    role: 'user',
    content: '请查收',
    metadata: { attachment: { filename: '执照.pdf' } },
  })
  assert.equal(turn.chips[0].type, 'PDF')
  assert.equal(turn.text, '请查收')
})

test('sources are only real http links', () => {
  const cards = sourceCards([
    { title: '铁路投标保证金', url: 'https://www.example.com/bond' },
    { title: '坏链接', url: 'javascript:alert(1)' },
    { title: '缺链接' },
    { title: '重复', url: 'https://www.example.com/bond' },
  ])
  assert.equal(cards.length, 1)
  assert.equal(cards[0].title, '铁路投标保证金')
  assert.equal(cards[0].domain, 'example.com')
})

test('markdown keeps headings, lists and code', () => {
  const blocks = parseMarkdown('# 标题\n\n- 一项\n- 两项\n\n```js\nconst a = 1\n```\n\n见 [说明](https://example.com/a)')
  assert.equal(blocks[0].type, 'heading')
  assert.equal(blocks[1].type, 'ul')
  assert.equal(blocks[2].type, 'code')
  assert.equal(blocks[2].lang, 'js')
  assert.match(blocks[3].text, /说明/)
})

test('chip payload drops empty names', () => {
  assert.deepEqual(chipPayload([{ name: 'a.zip', kind: 'file' }, { name: '  ' }]), [
    { name: 'a.zip', kind: 'file', type: 'ZIP' },
  ])
})
