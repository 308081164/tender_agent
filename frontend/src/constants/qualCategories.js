/** 与 backend qual_extract.QUAL_CATEGORIES、agent DOC_TYPE_TO_QUAL_CATEGORY 一致 */
export const QUAL_CATEGORY_OPTIONS = [
  { value: '企业资质包', description: '营业执照、资质证书、安全生产许可等' },
  { value: '业绩包', description: '中标通知、合同、验收证明等业绩材料' },
  { value: '人员资质包', description: '身份证、职称、建造师、关键岗位人员证书' },
  { value: '财务包', description: '财务报表、审计报告、开户许可等' },
  { value: '信誉包', description: '信用报告、无违法违纪声明等' },
  { value: '授权包', description: '法人授权书、投标授权委托等' },
  { value: '其他', description: '未归入以上六类的补充材料' },
]

export const QUAL_CATEGORY_VALUES = QUAL_CATEGORY_OPTIONS.map((o) => o.value)

/** API 可能含历史/自定义分类，排在七大类之后 */
export function mergeQualCategories(fromApi = []) {
  const seen = new Set()
  const out = []
  for (const c of [...QUAL_CATEGORY_VALUES, ...(fromApi || [])]) {
    if (c && !seen.has(c)) {
      seen.add(c)
      out.push(c)
    }
  }
  return out
}
