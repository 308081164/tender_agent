export const ADMIN_MODULES = [
  { path: 'company', label: '企业档案', desc: '基本信息与默认值' },
  { path: 'fields', label: '字段定义', desc: '录入字段与枚举' },
  { path: 'templates', label: '模板管理', desc: '工程化模板与历史标书' },
  { path: 'qualifications', label: '资质库', desc: '七大类资质材料' },
  { path: 'checklist', label: '校验清单', desc: '导出前条目校验' },
  { path: 'faqs', label: 'FAQ', desc: '企业问答知识库' },
  { path: 'import', label: '导入/备份', desc: '客户包与 JSON 备份' },
]

export const TEMPLATE_CODES = [
  { value: 'common', label: '通用 common' },
  { value: 'tpl1', label: '模板1 tpl1' },
  { value: 'tpl3', label: '模板3 tpl3' },
]

export const FIELD_TYPES = ['文本', '数字', '日期', '金额', '下拉', '下拉选项', '多行文本']

export const TEMPLATE_KINDS = [
  { value: 'template', label: '工程化模板' },
  { value: 'history', label: '历史标书' },
  { value: 'skeleton', label: '骨架模板' },
]

export const CHECKLIST_REQUIRED = ['必含', '条件必含', '选填']

export const DESENSITIZED_COMPANY_KEYS = new Set([
  'legal_id_no', 'bank_account', 'recent_revenue',
])
