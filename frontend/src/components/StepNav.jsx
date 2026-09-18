import React from 'react'
import { STEPS } from '../constants'

export default function StepNav({ project, activeStep, onGoStep }) {
  const currentStep = project?.current_step || 1

  return (
    <div className="stepbar">
      {STEPS.map((s) => {
        const reachable = s.step <= currentStep
        const done = currentStep > s.step
          || (currentStep === 6 && s.step === 6 && project.status === 'exported')
        const active = activeStep === s.step
        return (
          <button
            type="button"
            key={s.step}
            className={`stepbar-item ${active ? 'active' : ''} ${done && !active ? 'done' : ''} ${reachable ? 'clickable' : ''}`}
            onClick={() => reachable && onGoStep?.(s.step)}
            disabled={!reachable}
          >
            <strong>{String(s.step).padStart(2, '0')}{done && !active ? ' ✓' : ''}</strong>
            {s.name}
          </button>
        )
      })}
    </div>
  )
}
