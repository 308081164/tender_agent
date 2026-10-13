import React from 'react'
import { WORKSPACE_PHASES, workspacePhaseFromStep } from '../../utils/projectRouting'

export default function WorkspaceStepBar({ project, activePhase, onPhaseClick }) {
  const derived = workspacePhaseFromStep(project?.current_step, project?.status)
  const current = activePhase || derived

  return (
    <div className="workspace-phase-bar stepbar">
      {WORKSPACE_PHASES.map((phase, idx) => {
        const curIdx = WORKSPACE_PHASES.findIndex((p) => p.id === current)
        const active = phase.id === current
        const done = idx < curIdx || (project?.status === 'exported' && phase.id === 'export')
        const clickable = !!onPhaseClick
        return (
          <button
            type="button"
            key={phase.id}
            className={`stepbar-item workspace-phase-item ${active ? 'active' : ''} ${done ? 'done' : ''} ${clickable ? 'clickable' : ''}`}
            onClick={() => onPhaseClick?.(phase.id)}
            disabled={!clickable}
          >
            <strong>{String(idx + 1).padStart(2, '0')}{done && !active ? ' ✓' : ''}</strong>
            {phase.name}
          </button>
        )
      })}
    </div>
  )
}
