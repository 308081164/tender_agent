/** 报价、工期等需人工核实的敏感字段 key */
export const SENSITIVE_FIELD_KEYS = new Set([
  'bid_amount',
  'bid_amount_upper',
  'bid_amount_lower',
  'duration',
  'warranty_period',
  'delivery_period',
  'project_manager',
  'bid_date',
  'sign_date',
])

const SENSITIVE_MODULES = new Set(['报价', '投标报价', '工期与服务'])

/** 是否应在向导中标注「请核实」并高亮 */
export function isVerifyField(fieldDef) {
  if (!fieldDef) return false
  if (fieldDef.desensitized) return true
  if (SENSITIVE_FIELD_KEYS.has(fieldDef.key)) return true
  return SENSITIVE_MODULES.has(fieldDef.module)
}

/** 用字段定义中的有效默认值补齐空缺（不覆盖用户已填内容） */
export function mergeFieldDefaults(fields, fieldDefs) {
  const next = { ...(fields || {}) }
  for (const f of fieldDefs || []) {
    if (next[f.key]) continue
    const val = f.effective_default || f.default_value || ''
    if (val) next[f.key] = val
  }
  return next
}
