import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  legacyWorkspaceRedirectPath,
  LEGACY_EXPORT_STEP,
  projectAgentChatPath,
  projectContinuePath,
  step2EnterAgentDestination,
  step2EnterAgentRequest,
  step2EnterAgentStatus,
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

test('step 2 save opens this project Agent page and does not target export', () => {
  const body = step2EnterAgentRequest({ project_name: '新城智慧交通' })
  assert.equal(body.enter_agent, true)
  assert.equal(body.advance, false)
  assert.equal(body.current_step, 2)
  assert.notEqual(body.current_step, LEGACY_EXPORT_STEP)
  assert.equal(body.fields.project_name, '新城智慧交通')

  const path = step2EnterAgentDestination(15)
  assert.equal(path, '/chat?project=15')
  assert.equal(path.includes('/workspace'), false)
  assert.equal(/\/step\/[3-6]/.test(path), false)
  assert.equal(projectAgentChatPath(15), path)
  assert.equal(projectContinuePath({ id: 15, current_step: 3 }), path)

  const status = step2EnterAgentStatus()
  assert.equal(status, '已保存，进入 Agent 对话')
  assert.equal(status.includes('导出'), false)
  assert.equal(status.includes('审查'), false)
  assert.equal(status.includes('创作工作台'), false)
  assert.notEqual(status, '已保存并进入：导出')
})

test('wizard step 2 keeps a single button into the project Agent', () => {
  const src = readFileSync(new URL('../pages/WizardPage.jsx', import.meta.url), 'utf8')
  const start = src.indexOf('{step === 2 &&')
  const end = src.indexOf('{step === 3 &&')
  assert.equal(start > 0 && end > start, true)
  const step2 = src.slice(start, end)
  assert.equal(step2.includes('保存并进入 Agent 对话'), true)
  assert.equal(step2.includes('返回上一步'), true)
  assert.equal(step2.includes('保存本步'), true)
  assert.equal(step2.includes('打开 Agent 对话'), false)
  assert.equal(step2.includes('创作工作台'), false)
  assert.equal(step2.includes('保存并进入导出'), false)
  assert.equal(step2.includes('/workspace'), false)

  const fnStart = src.indexOf('const confirmFields')
  const fnEnd = src.indexOf('const doGenerate')
  const fn = src.slice(fnStart, fnEnd)
  assert.match(fn, /enterAgent:\s*true/)
  assert.match(fn, /step2EnterAgentDestination\(/)
  assert.doesNotMatch(fn, /advance:\s*true/)
  assert.doesNotMatch(fn, /\/projects\/\$\{/)
  assert.doesNotMatch(fn, /workspace/)
  assert.doesNotMatch(fn, /已保存并进入：导出/)

  const hook = readFileSync(new URL('../hooks/useProject.js', import.meta.url), 'utf8')
  assert.match(hook, /step2EnterAgentRequest/)
  assert.match(hook, /step2EnterAgentStatus/)
  assert.match(hook, /payload\.advance = handoff\.advance/)
  assert.match(hook, /payload\.enter_agent = handoff\.enter_agent/)
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
