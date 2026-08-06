import React from 'react'
import { STEPS } from '../constants'

export default function StepNav({ project, activeStep, onGoStep }) {
  const currentStep = project?.current_step || 1

  return (
    <ul className="step-list">
      {STEPS.map((s) => {
        const reachable = s.step <= currentStep
        const done = currentStep > s.step
          || (currentStep === 6 && s.step === 6 && project.status === 'exported')
        const active = activeStep === s.step
        return (
          <li
            key={s.step}
            className={`step-item ${active ? 'active' : ''} ${done && !active ? 'done' : ''} ${reachable ? 'clickable' : ''}`}
            onClick={() => reachable && onGoStep?.(s.step)}
          >
            <span className="step-num">{done && !active ? '✓' : s.step}</span>
            <span>{s.name}</span>
          </li>
        )
      })}
    </ul>
  )
}
