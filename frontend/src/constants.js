import { WIZARD_STEPS, WORKSPACE_PHASES } from './utils/projectRouting'

/** @deprecated 向导页请用 WIZARD_STEPS；工作台用 WORKSPACE_PHASES */
export const STEPS = [
  ...WIZARD_STEPS,
  ...WORKSPACE_PHASES.map((p, i) => ({ step: i + 3, name: p.name })),
]

export { WIZARD_STEPS, WORKSPACE_PHASES }
