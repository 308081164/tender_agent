import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { sessionFromProjectBind } from './projectSession.js'

test('wizard bind uses nested session id from POST /projects/:id/sessions', () => {
  const payload = {
    session: { id: 12, title: '新建标书', workspace: { project_id: 4 } },
    project_id: 4,
  }
  const sess = sessionFromProjectBind(payload)
  assert.equal(sess.id, 12)
  assert.equal(payload.id, undefined)
  assert.equal(sessionFromProjectBind(null), null)
  assert.equal(sessionFromProjectBind({ project_id: 4 }), null)
  assert.equal(sessionFromProjectBind({ id: 12 }), null)
})

test('project wizard bind does not request chat session undefined', () => {
  const src = readFileSync(new URL('../hooks/useChat.js', import.meta.url), 'utf8')
  assert.match(src, /sessionFromProjectBind/)
  assert.doesNotMatch(
    src,
    /ensureProjectSession\(projectId\)\s*\n\s*setSessionId\(sess\.id\)/,
  )
})
