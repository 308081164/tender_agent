import React, { useEffect, useState } from 'react'
import { api } from '../api/client'

export default function TableSlotsEditor({ projectId, fields, onChange, onGenerate, loading }) {
  const [slots, setSlots] = useState([])
  const [rowsByBind, setRowsByBind] = useState({})

  useEffect(() => {
    if (!projectId) return
    api.getTableSlots(projectId).then((res) => {
      setSlots(res.slots || [])
      setRowsByBind(res.rows || {})
    }).catch(() => {
      setSlots([])
      setRowsByBind({})
    })
  }, [projectId])

  if (!slots.length) return null

  const updateCell = (bind, rowIdx, col, value) => {
    const next = { ...rowsByBind }
    const rows = [...(next[bind] || [])]
    while (rows.length <= rowIdx) rows.push({})
    rows[rowIdx] = { ...rows[rowIdx], [col]: value }
    next[bind] = rows
    setRowsByBind(next)
    onChange?.({ ...fields, [bind]: rows })
  }

  const addRow = (bind, columns) => {
    const next = { ...rowsByBind }
    const row = {}
    columns.forEach((c) => { row[c] = '' })
    next[bind] = [...(next[bind] || []), row]
    setRowsByBind(next)
    onChange?.({ ...fields, [bind]: next[bind] })
  }

  const saveBind = async (bind) => {
    await api.updateTableSlots(projectId, bind, rowsByBind[bind] || [])
  }

  return (
    <div className="table-slots-editor" style={{ marginTop: 16 }}>
      <h3>表格数据</h3>
      <p className="lead" style={{ marginBottom: 12 }}>根据模板表格槽填写行数据，或使用 AI 自动生成。</p>
      {slots.map((slot) => (
        <div className="card-block" key={slot.id} style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <strong>{slot.title || slot.bind}</strong>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" className="ghost" disabled={loading}
                onClick={() => addRow(slot.bind, slot.columns)}>添加行</button>
              <button type="button" className="secondary" disabled={loading}
                onClick={() => saveBind(slot.bind)}>保存表格</button>
            </div>
          </div>
          <table className="admin-table" style={{ width: '100%' }}>
            <thead>
              <tr>{(slot.columns || []).map((c) => <th key={c}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {(rowsByBind[slot.bind] || []).map((row, ri) => (
                <tr key={ri}>
                  {(slot.columns || []).map((col) => (
                    <td key={col}>
                      <input
                        value={row[col] || ''}
                        disabled={loading}
                        onChange={(e) => updateCell(slot.bind, ri, col, e.target.value)}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <button type="button" onClick={onGenerate} disabled={loading}>AI 生成全部表格</button>
    </div>
  )
}
