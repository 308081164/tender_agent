import React from 'react'

export default function SnapshotPanel({ snapshots, onRollback }) {
  return (
    <div>
      <h3>步骤快照</h3>
      <div className="project-list">
        {snapshots.length === 0 && <div className="empty">暂无快照</div>}
        {snapshots.slice(0, 8).map((s) => (
          <div className="project-row" key={s.id} onClick={() => onRollback(s.id)}>
            <div>
              <strong>{s.step_name}</strong>
              <div style={{ color: 'var(--muted)', fontSize: 12 }}>{s.created_at}</div>
            </div>
            <span className="badge">回退</span>
          </div>
        ))}
      </div>
    </div>
  )
}
