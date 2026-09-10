import React from 'react'
import TemplatePickerCard from './TemplatePickerCard'
import MappingConfirmCard from './MappingConfirmCard'
import FieldCollectCard from './FieldCollectCard'
import TemplateInfoCard from './TemplateInfoCard'
import ProjectInfoCard from './ProjectInfoCard'
import ConfirmCard from './ConfirmCard'
import RequirementsCollectCard from './RequirementsCollectCard'
import DocReviewCard from './DocReviewCard'
import CardErrorBoundary from './CardErrorBoundary'

const RENDERERS = {
  template_picker: TemplatePickerCard,
  mapping_confirm: MappingConfirmCard,
  field_collect: FieldCollectCard,
  requirements_collect: RequirementsCollectCard,
  doc_review: DocReviewCard,
  template_info: TemplateInfoCard,
  project_info: ProjectInfoCard,
  confirm: ConfirmCard,
}

export default function ChatCards({ cards = [], message, onAction, actingCardId }) {
  if (!cards?.length) return null
  return (
    <div className="chat-cards">
      {cards.map((card) => {
        const Renderer = RENDERERS[card.type]
        if (!Renderer) return null
        return (
          <CardErrorBoundary key={card.id}>
            <Renderer
              card={card}
              message={message}
              acting={actingCardId === card.id}
              onAction={onAction}
            />
          </CardErrorBoundary>
        )
      })}
    </div>
  )
}
