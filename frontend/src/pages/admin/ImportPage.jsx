import React, { useState } from 'react'
import { useApp } from '../../App'
import { api } from '../../api/client'
import AdminPageHeader from '../../components/admin/AdminPageHeader'
import AdminConfirmDialog from '../../components/admin/AdminConfirmDialog'

export default function ImportPage() {
  const { showToast, refreshBaseData } = useApp()
  const [confirmForce, setConfirmForce] = useState(false)
  const [busy, setBusy] = useState(false)

  const doImport = async (force = false) => {
    setBusy(true)
    try {
      const r = await api.adminImport(force)
      await refreshBaseData?.()
      showToast(r.skipped ? '已有数据，已跳过（如需覆盖请强制导入）' : '导入完成，基础数据已刷新')
    } catch (e) {
      showToast(e.message)
    } finally {
      setBusy(false)
      setConfirmForce(false)
    }
  }

  const exportBackup = async () => {
    try {
      const snap = await api.adminExportSnapshot()
      const blob = new Blob([JSON.stringify(snap, null, 2)], { type: 'application/json' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `base-data-${Date.now()}.json`
      a.click()
      URL.revokeObjectURL(a.href)
      showToast('备份已下载')
    } catch (e) {
      showToast(e.message)
    }
  }

  return (
    <>
      <AdminPageHeader
        title="导入 / 备份"
        lead="从和远客户材料包重新导入，或导出当前基础数据 JSON 备份。"
      />
      <div className="card-block">
        <p>增量导入：若库中已有字段定义则跳过。强制导入会清空并覆盖全部基础数据（不影响已有标书项目）。</p>
        <div className="actions">
          <button type="button" disabled={busy} onClick={() => doImport(false)}>增量导入</button>
          <button type="button" className="secondary" disabled={busy} onClick={() => setConfirmForce(true)}>强制重新导入</button>
          <button type="button" className="ghost" onClick={exportBackup}>导出备份 JSON</button>
        </div>
      </div>
      <AdminConfirmDialog
        open={confirmForce}
        title="强制重新导入"
        message="将清空并覆盖企业档案、字段、模板、资质、清单与 FAQ。确认继续？"
        danger
        confirmLabel="确认覆盖"
        onCancel={() => setConfirmForce(false)}
        onConfirm={() => doImport(true)}
      />
    </>
  )
}
