export const ADMIN_MODULES = [
  { path: 'company', label: '企业档案', desc: '基本信息与默认值' },
  { path: 'fields', label: '字段定义', desc: '录入字段与枚举' },
  { path: 'templates', label: '模板管理', desc: '上传、工程化与模板详情' },
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
  { value: 'template', label: '基于空白模板创建' },
  { value: 'history', label: '基于完整标书创建' },
  { value: 'skeleton', label: '骨架模板' },
]

/** 列表分类与创建方式展示 */
export const TEMPLATE_SOURCE_LABELS = {
  history: '基于完整标书创建',
  skeleton: '基于空白模板创建',
  template: '工程化模板',
  tender_doc: '招标文件',
}

export const TEMPLATE_UPLOAD_OPTIONS = [
  {
    kind: 'history',
    title: '基于完整标书创建',
    description:
      '适用于已填写的完整投标文件。工程化时需标记项目名称、招标编号、金额等大量可变字段，完成后可基于快照做智能替换。',
  },
  {
    kind: 'skeleton',
    title: '基于空白模板创建',
    description:
      '适用于含编写规则、格式要求的空白或半空白模板。占位符较少、自由度更高；立项生成 AI 章节时会将模板全文作为参考上下文。',
  },
]

export function templateSourceLabel(kind) {
  return TEMPLATE_SOURCE_LABELS[kind] || kind || '—'
}

export const CHECKLIST_REQUIRED = ['必含', '条件必含', '选填']

export const DESENSITIZED_COMPANY_KEYS = new Set([
  'legal_id_no', 'bank_account', 'recent_revenue',
])
