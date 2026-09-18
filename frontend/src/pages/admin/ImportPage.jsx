import React, { useRef, useState } from 'react'
import { useApp } from '../../App'
import { api } from '../../api/client'
import AdminPageHeader from '../../components/admin/AdminPageHeader'
import AdminConfirmDialog from '../../components/admin/AdminConfirmDialog'

export default function ImportPage() {
  const { showToast, refreshBaseData } = useApp()
  const [confirmForce, setConfirmForce] = useState(false)
  const [confirmImportPack, setConfirmImportPack] = useState(false)
  const [busy, setBusy] = useState(false)
  const packInputRef = useRef(null)
  const [pendingPack, setPendingPack] = useState(null)

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

  const exportMigrationPack = async () => {
    setBusy(true)
    try {
      const blob = await api.adminExportPack()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `tender-agent-migration-${Date.now()}.zip`
      a.click()
      URL.revokeObjectURL(a.href)
      showToast('迁移包已导出（含全部附件）')
    } catch (e) {
      showToast(e.message)
    } finally {
      setBusy(false)
    }
  }

  const onPackSelected = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setPendingPack(file)
    setConfirmImportPack(true)
    e.target.value = ''
  }

  const doImportPack = async () => {
    if (!pendingPack) return
    setBusy(true)
    try {
      const r = await api.adminImportPack(pendingPack, true)
      await refreshBaseData?.()
      const c = r.counts || {}
      showToast(`迁移完成：字段 ${c.fields || 0}、模板 ${c.templates || 0}、资质 ${c.qualifications || 0}`)
    } catch (e) {
      showToast(e.message)
    } finally {
      setBusy(false)
      setConfirmImportPack(false)
      setPendingPack(null)
    }
  }

  return (
    <>
      <AdminPageHeader
        title="导入 / 备份"
        lead="一键导出迁移包到新电脑导入，或导出 JSON 元数据备份。"
      />
      <div className="card-block">
        <h3>数据迁移（推荐）</h3>
        <p>迁移包包含企业档案、字段、模板、资质、清单、FAQ 及全部附件文件，适用于换机快速恢复。</p>
        <div className="actions">
          <button type="button" disabled={busy} onClick={exportMigrationPack}>一键导出迁移包</button>
          <button type="button" className="secondary" disabled={busy} onClick={() => packInputRef.current?.click()}>
            从迁移包导入
          </button>
          <input ref={packInputRef} type="file" accept=".zip" hidden onChange={onPackSelected} />
        </div>
      </div>
      <div className="card-block">
        <h3>客户材料包 / JSON 备份</h3>
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
      <AdminConfirmDialog
        open={confirmImportPack}
        title="导入迁移包"
        message={`将覆盖当前全部基础数据（保留已有标书项目）。确认导入 ${pendingPack?.name || '迁移包'}？`}
        danger
        confirmLabel="确认导入"
        onCancel={() => { setConfirmImportPack(false); setPendingPack(null) }}
        onConfirm={doImportPack}
      />
    </>
  )
}
