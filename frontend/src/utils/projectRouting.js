/** 向导仅步骤 1–2；步骤 ≥3 统一进入项目创作工作台（双栏）。 */

export const WIZARD_MAX_STEP = 2

export const WIZARD_STEPS = [
  { step: 1, name: '选择起点' },
  { step: 2, name: '信息录入' },
]

export const WORKSPACE_PHASES = [
  { id: 'create', name: '创作', minStep: 3, maxStep: 3 },
  { id: 'review', name: '审查', minStep: 4, maxStep: 5 },
  { id: 'export', name: '导出', minStep: 6, maxStep: 6 },
]

export function isWorkspaceStep(currentStep) {
  return (currentStep || 1) >= 3
}

/** 工作台「继续」、向导 step≥3 等统一落点 */
export function projectContinuePath(project) {
  const id = project?.id
  if (!id) return '/'
  const step = project.current_step || 1
  if (step <= WIZARD_MAX_STEP) {
    return `/projects/${id}/step/${Math.min(step, WIZARD_MAX_STEP)}`
  }
  return `/projects/${id}/workspace`
}

export function workspacePhaseFromStep(currentStep, status) {
  if (status === 'exported') return 'export'
  const step = currentStep || 3
  if (step >= 6) return 'export'
  if (step >= 4) return 'review'
  return 'create'
}

export function workspacePhaseIndex(phaseId) {
  return WORKSPACE_PHASES.findIndex((p) => p.id === phaseId)
}

export function stepForWorkspacePhase(phaseId) {
  const phase = WORKSPACE_PHASES.find((p) => p.id === phaseId)
  return phase?.minStep ?? 3
}
