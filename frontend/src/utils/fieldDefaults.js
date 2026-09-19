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

/** 是否应以企业档案有效默认值覆盖当前值 */
function shouldApplyDefault(current, effective, staticDefault) {
  if (!effective) return !current
  if (!current) return true
  if (staticDefault && current === staticDefault && effective !== staticDefault) return true
  return false
}

/** 用字段定义中的有效默认值补齐空缺（不覆盖用户已填内容） */
export function mergeFieldDefaults(fields, fieldDefs) {
  const next = { ...(fields || {}) }
  for (const f of fieldDefs || []) {
    const effective = f.effective_default || ''
    const staticDefault = f.default_value || ''
    const current = next[f.key]
    if (!shouldApplyDefault(current, effective, staticDefault)) continue
    const val = effective || staticDefault
    if (val) next[f.key] = val
  }
  return next
}
