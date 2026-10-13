import React from 'react'
import { WIZARD_STEPS } from '../utils/projectRouting'

export default function StepNav({ project, activeStep, onGoStep, steps = WIZARD_STEPS }) {
  const currentStep = Math.min(project?.current_step || 1, steps.length ? steps[steps.length - 1].step : 2)

  return (
    <div className="stepbar">
      {steps.map((s) => {
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
