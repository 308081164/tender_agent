import React, { useEffect, useState } from 'react'
import { useApp } from '../../App'
import { api } from '../../api/client'
import AdminPageHeader from '../../components/admin/AdminPageHeader'
import AdminFormSection, { AdminField } from '../../components/admin/AdminFormSection'
import { DESENSITIZED_COMPANY_KEYS } from '../../constants/admin'

const BASIC_FIELDS = [
  ['full_name', '企业全称'], ['short_name', '简称'], ['credit_code', '信用代码'],
  ['register_address', '注册地址'], ['office_address', '办公地址'],
  ['phone', '电话'], ['fax', '传真'], ['email', '邮箱'], ['website', '网址'], ['postcode', '邮编'],
]

const LEGAL_BANK_FIELDS = [
  ['legal_name', '法人'], ['legal_gender', '性别'], ['legal_age', '年龄'], ['legal_title', '职务'],
  ['legal_id_no', '法人身份证号', true], ['registered_capital', '注册资本'], ['founded_date', '成立日期'],
  ['bank_name', '开户行'], ['bank_account', '银行账号', true], ['recent_revenue', '近三年营业额', true],
  ['related_companies', '关联企业'],
]

const LONG_FIELDS = [
  ['intro', '企业简介'], ['business_scope', '主营业务'],
  ['qual_overview', '资质概述'], ['typical_projects', '典型项目说明'], ['ai_style_notes', 'AI 风格说明'],
]

export default function CompanyPage() {
  const { showToast, refreshBaseData } = useApp()
  const [company, setCompany] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.getCompany().then(setCompany).catch((e) => showToast(e.message))
  }, [showToast])

  const save = async () => {
    setSaving(true)
    try {
      const saved = await api.updateCompany(company)
      setCompany(saved)
      await refreshBaseData?.()
      showToast('企业档案已保存，新建标书将使用最新默认值')
    } catch (e) {
      showToast(e.message)
    } finally {
      setSaving(false)
    }
  }

  if (!company) return <div className="admin-loading">加载中…</div>

  const renderInput = ([key, label, desensitized]) => (
    <AdminField
      key={key}
      label={label}
      hint={desensitized || DESENSITIZED_COMPANY_KEYS.has(key) ? '请核实' : ''}
    >
      <input
        className={desensitized || DESENSITIZED_COMPANY_KEYS.has(key) ? 'desensitized' : undefined}
        value={company[key] || ''}
        onChange={(e) => setCompany({ ...company, [key]: e.target.value })}
      />
    </AdminField>
  )

  return (
    <>
      <AdminPageHeader
        title="企业档案"
        lead="维护企业基本信息与 AI 上下文。脱敏字段导出前请在向导中再次核实。"
        actions={<button type="button" onClick={save} disabled={saving}>保存企业档案</button>}
      />
      <div className="card-block">
        <AdminFormSection title="基本信息">{BASIC_FIELDS.map(renderInput)}</AdminFormSection>
        <AdminFormSection title="法人与银行">{LEGAL_BANK_FIELDS.map(renderInput)}</AdminFormSection>
        <AdminFormSection title="长文本与 AI 参考">
          {LONG_FIELDS.map(([key, label]) => (
            <AdminField key={key} label={label} full>
              <textarea
                rows={key === 'typical_projects' || key === 'ai_style_notes' ? 8 : 4}
                value={company[key] || ''}
                onChange={(e) => setCompany({ ...company, [key]: e.target.value })}
              />
            </AdminField>
          ))}
        </AdminFormSection>
      </div>
    </>
  )
}
