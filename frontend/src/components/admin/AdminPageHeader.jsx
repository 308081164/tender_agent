import React from 'react'

export default function AdminPageHeader({ title, lead, actions }) {
  return (
    <header className="admin-page-header">
      <div>
        <h2>{title}</h2>
        {lead ? <p className="lead">{lead}</p> : null}
      </div>
      {actions ? <div className="admin-page-actions">{actions}</div> : null}
    </header>
  )
}
