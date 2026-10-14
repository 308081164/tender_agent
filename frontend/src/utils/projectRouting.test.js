import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  legacyWorkspaceRedirectPath,
  projectAgentChatPath,
  projectContinuePath,
} from './projectRouting.js'

test('post-wizard continue opens Agent chat instead of the creation workspace', () => {
  assert.equal(projectContinuePath({ id: 7, current_step: 1 }), '/projects/7/step/1')
  assert.equal(projectContinuePath({ id: 7, current_step: 2 }), '/projects/7/step/2')
  const later = projectContinuePath({ id: 7, current_step: 4 })
  assert.equal(later, '/chat?project=7')
  assert.equal(later.includes('/workspace'), false)
  assert.equal(projectAgentChatPath(7), later)
})

test('legacy workspace route redirects to Agent chat', () => {
  assert.equal(legacyWorkspaceRedirectPath('12'), '/chat?project=12')
  const main = readFileSync(new URL('../main.jsx', import.meta.url), 'utf8')
  assert.match(main, /path="projects\/:id\/workspace"/)
  assert.match(main, /LegacyWorkspaceRedirect/)
  assert.match(main, /projectAgentChatPath/)
  assert.match(main, /<Navigate/)
  assert.doesNotMatch(main, /ProjectWorkspacePage/)
})

test('visible entry points do not link to the creation workspace', () => {
  const files = [
    '../pages/WizardPage.jsx',
    '../pages/ChatPage.jsx',
    '../pages/HomePage.jsx',
    '../pages/PreviewPage.jsx',
    '../components/FloatingChat.jsx',
    '../components/ChatDrawer.jsx',
    '../components/project/CreateProjectHubModal.jsx',
    '../App.jsx',
  ]
  for (const rel of files) {
    const text = readFileSync(new URL(rel, import.meta.url), 'utf8')
    assert.doesNotMatch(text, /创作工作台/, rel)
    assert.doesNotMatch(text, /\/projects\/\$\{[^}]+\}\/workspace/, rel)
    assert.doesNotMatch(text, /打开创作工作台/, rel)
  }
})
