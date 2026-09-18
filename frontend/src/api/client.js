const BASE = '/api'

function buildQuery(params = {}) {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') sp.set(k, String(v))
  })
  const s = sp.toString()
  return s ? `?${s}` : ''
}

async function readErrorDetail(res) {
  const text = await res.text()
  if (!text) return `请求失败 ${res.status}`
  try {
    const data = JSON.parse(text)
    const d = data.detail
    if (typeof d === 'string') return d
    if (d?.message) return d.message
    if (d) return JSON.stringify(d)
    return JSON.stringify(data)
  } catch {
    return text
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    throw new Error(await readErrorDetail(res))
  }
  if (res.status === 204) return null
  const type = res.headers.get('content-type') || ''
  if (type.includes('application/json')) return res.json()
  return res
}

async function fetchBlob(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) {
    throw new Error(await readErrorDetail(res))
  }
  return res.blob()
}

export const api = {
  health: () => request('/health'),
  systemCheck: () => request('/system/check'),
  steps: () => request('/meta/steps'),
  templates: () => request('/templates'),
  fields: () => request('/fields'),
  qualifications: (category) =>
    request(`/qualifications${category ? `?category=${encodeURIComponent(category)}` : ''}`),
  qualCategories: () => request('/qualifications/categories'),
  checklist: () => request('/checklist'),
  projects: () => request('/projects'),
  getProject: (id) => request(`/projects/${id}`),
  createProject: (body) => request('/projects', { method: 'POST', body: JSON.stringify(body) }),
  deleteProject: (id) => request(`/projects/${id}`, { method: 'DELETE' }),
  confirmStep1: (id, body) => request(`/projects/${id}/step1`, { method: 'POST', body: JSON.stringify(body) }),
  updateFields: (id, fields, confirm = false) =>
    request(`/projects/${id}/fields`, { method: 'PUT', body: JSON.stringify({ fields, confirm }) }),
  generate: (id, chapters) =>
    request(`/projects/${id}/generate`, { method: 'POST', body: JSON.stringify({ chapters }) }),
  regenerate: (id, key) => request(`/projects/${id}/generate/${encodeURIComponent(key)}`, { method: 'POST' }),
  confirmAi: (id) => request(`/projects/${id}/confirm-ai`, { method: 'POST' }),
  insertQuals: (id, qualification_ids) =>
    request(`/projects/${id}/insert-quals`, { method: 'POST', body: JSON.stringify({ qualification_ids }) }),
  validate: (id) => request(`/projects/${id}/validate`, { method: 'POST' }),
  docReview: (id) => request(`/projects/${id}/doc-review`, { method: 'POST' }),
  compose: (id, requirements) =>
    request(`/projects/${id}/compose`, {
      method: 'POST',
      body: JSON.stringify({ requirements }),
    }),
  getTableSlots: (id) => request(`/projects/${id}/table-slots`),
  updateTableSlots: (id, bind, rows) =>
    request(`/projects/${id}/table-slots`, {
      method: 'PUT',
      body: JSON.stringify({ bind, rows }),
    }),
  generateTables: (id, requirements = '') =>
    request(`/projects/${id}/generate-tables`, {
      method: 'POST',
      body: JSON.stringify({ requirements }),
    }),
  getTemplateManifest: (id) => request(`/admin/templates/${id}/manifest`),
  updateTemplateImageBinding: (id, blockId, bind) =>
    request(`/admin/templates/${id}/manifest/image-bindings`, {
      method: 'PUT',
      body: JSON.stringify({ block_id: blockId, bind }),
    }),
  analyzeTemplateManifest: (id) =>
    request(`/admin/templates/${id}/analyze-manifest`, { method: 'POST' }),
  exportDoc: (id) => fetchBlob(`/projects/${id}/export`),
  listExports: (id) => request(`/projects/${id}/exports`),
  previewExport: (projectId, exportId) =>
    request(`/projects/${projectId}/exports/${exportId}/preview`),
  previewPdfUrl: (projectId, exportId) =>
    `${BASE}/projects/${projectId}/exports/${exportId}/preview.pdf`,
  downloadExportUrl: (projectId, exportId, inline = false) =>
    `${BASE}/projects/${projectId}/exports/${exportId}/download${inline ? '?inline=1' : ''}`,
  downloadExport: (projectId, exportId) =>
    fetchBlob(`/projects/${projectId}/exports/${exportId}/download`),
  snapshots: (id) => request(`/projects/${id}/snapshots`),
  rollback: (id, snapshot_id) =>
    request(`/projects/${id}/rollback`, { method: 'POST', body: JSON.stringify({ snapshot_id }) }),
  ask: (question, session_id) =>
    request('/chatbot/ask', {
      method: 'POST',
      body: JSON.stringify({ question, ...(session_id ? { session_id } : {}) }),
    }),
  listChatSessions: () => request('/chat/sessions'),
  createChatSession: (title = '新对话') =>
    request('/chat/sessions', { method: 'POST', body: JSON.stringify({ title }) }),
  getChatSession: (id) => request(`/chat/sessions/${id}`),
  deleteChatSession: (id) => request(`/chat/sessions/${id}`, { method: 'DELETE' }),
  renameChatSession: (id, title) =>
    request(`/chat/sessions/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
  getChatFeatures: () => request('/chat/features'),
  uploadChatFile: async (sessionId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/chat/sessions/${sessionId}/upload`, { method: 'POST', body: fd })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },
  detectTemplatePlaceholders: (id) =>
    request(`/admin/templates/${id}/detect-placeholders`, { method: 'POST' }),
  searchMappingResources: (q = '') =>
    request(`/admin/mapping-resources${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  adminFieldModules: () => request('/admin/field-modules'),
  getWorkflowPlan: (projectId) => request(`/projects/${projectId}/workflow-plan`),
  guidedIntake: (projectId, answered = {}) =>
    request(`/projects/${projectId}/guided-intake`, {
      method: 'POST',
      body: JSON.stringify({ answered }),
    }),
  previewTemplateMappingsPdf: async (id, mappings) => {
    const res = await fetch(`${BASE}/admin/templates/${id}/preview-mappings.pdf`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mappings }),
    })
    if (!res.ok) {
      let detail = ''
      try { detail = await res.text() } catch { /* ignore */ }
      throw new Error(detail || `PDF 预览失败 ${res.status}`)
    }
    return URL.createObjectURL(await res.blob())
  },
  applyTemplatePlaceholders: (id, mappings) =>
    request(`/admin/templates/${id}/apply-placeholders`, {
      method: 'POST',
      body: JSON.stringify({ mappings }),
    }),
  listChatMessages: (id) => request(`/chat/sessions/${id}/messages`),
  sendChatMessage: (sessionId, content, context = null) =>
    request(`/chat/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content, context }),
    }),
  getChatWorkspace: (sessionId) => request(`/chat/sessions/${sessionId}/workspace`),
  sendChatAction: (sessionId, body) =>
    request(`/chat/sessions/${sessionId}/actions`, { method: 'POST', body: JSON.stringify(body) }),
  getOnlyOfficeConfig: (sessionId) => request(`/chat/sessions/${sessionId}/onlyoffice/config`),
  getOnlyOfficeStatus: () => request('/onlyoffice/status'),
  updateWorkspaceParagraph: (sessionId, paragraphIndex, text) =>
    request(`/chat/sessions/${sessionId}/workspace/paragraph`, {
      method: 'POST',
      body: JSON.stringify({ paragraph_index: paragraphIndex, text }),
    }),
  previewTemplateMappings: (id, mappings) =>
    request(`/admin/templates/${id}/preview-mappings`, {
      method: 'POST',
      body: JSON.stringify({ mappings }),
    }),
  faqs: () => request('/chatbot/faqs'),
  getSettings: () => request('/settings'),
  updateSettings: (body) => request('/settings', { method: 'PUT', body: JSON.stringify(body) }),
  testProvider: (provider) => request('/settings/test', { method: 'POST', body: JSON.stringify({ provider }) }),
  saveProgress: (id, body) => request(`/projects/${id}/save`, { method: 'POST', body: JSON.stringify(body) }),
  getCompany: () => request('/company'),
  checklistByTemplate: (template_code) =>
    request(`/checklist${template_code ? `?template_code=${encodeURIComponent(template_code)}` : ''}`),
  fieldsByTemplate: (template_code) =>
    request(`/fields${template_code ? `?template_code=${encodeURIComponent(template_code)}` : ''}`),

  // Admin
  updateCompany: (body) => request('/admin/company', { method: 'PUT', body: JSON.stringify(body) }),
  adminFields: (params = {}) => request(`/admin/fields${buildQuery({
    page: params.page,
    page_size: params.pageSize,
    q: params.q,
    template_code: params.template_code,
  })}`),
  getField: (id) => request(`/admin/fields/${id}`),
  createField: (body) => request('/admin/fields', { method: 'POST', body: JSON.stringify(body) }),
  updateField: (id, body) => request(`/admin/fields/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteField: (id) => request(`/admin/fields/${id}`, { method: 'DELETE' }),
  adminTemplates: (params = {}) => request(`/admin/templates${buildQuery({
    page: params.page,
    page_size: params.pageSize,
    q: params.q,
    kind: params.kind,
    template_code: params.template_code,
    enabled: params.enabled,
  })}`),
  getTemplate: (id) => request(`/admin/templates/${id}`),
  updateTemplate: (id, body) => request(`/admin/templates/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteTemplate: (id) => request(`/admin/templates/${id}`, { method: 'DELETE' }),
  adminTemplateDownloadUrl: (id) => `${BASE}/admin/templates/${id}/download`,
  adminTemplatePreview: (id) => request(`/admin/templates/${id}/preview`),
  adminTemplatePreviewPdfUrl: (id) => `${BASE}/admin/templates/${id}/preview.pdf`,
  uploadTemplate: async (file, meta = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    const qs = new URLSearchParams(meta).toString()
    const res = await fetch(`${BASE}/admin/templates/upload?${qs}`, { method: 'POST', body: fd })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },
  adminQuals: (params = {}) => request(`/admin/qualifications${buildQuery({
    page: params.page,
    page_size: params.pageSize,
    q: params.q,
    category: params.category,
    status: params.status,
    sort_by: params.sortBy,
    sort_dir: params.sortDir,
  })}`),
  getQual: (id) => request(`/admin/qualifications/${id}`),
  createQual: (body) => request('/admin/qualifications', { method: 'POST', body: JSON.stringify(body) }),
  updateQual: (id, body) => request(`/admin/qualifications/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteQual: (id) => request(`/admin/qualifications/${id}`, { method: 'DELETE' }),
  adminQualFileUrl: (id, inline = false) =>
    `${BASE}/admin/qualifications/${id}/file${inline ? '?inline=true' : ''}`,
  replaceQualFile: async (id, file) => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/admin/qualifications/${id}/file`, { method: 'POST', body: fd })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },
  adminChecklist: (params = {}) => request(`/admin/checklist${buildQuery({
    page: params.page,
    page_size: params.pageSize,
    q: params.q,
    template_code: params.template_code,
  })}`),
  getChecklistItem: (id) => request(`/admin/checklist/${id}`),
  createChecklist: (body) => request('/admin/checklist', { method: 'POST', body: JSON.stringify(body) }),
  updateChecklist: (id, body) => request(`/admin/checklist/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteChecklist: (id) => request(`/admin/checklist/${id}`, { method: 'DELETE' }),
  adminFaqs: (params = {}) => request(`/admin/faqs${buildQuery({
    page: params.page,
    page_size: params.pageSize,
    q: params.q,
    category: params.category,
  })}`),
  getFaq: (id) => request(`/admin/faqs/${id}`),
  createFaq: (body) => request('/admin/faqs', { method: 'POST', body: JSON.stringify(body) }),
  updateFaq: (id, body) => request(`/admin/faqs/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteFaq: (id) => request(`/admin/faqs/${id}`, { method: 'DELETE' }),
  adminImport: (force = false) => request('/admin/import', { method: 'POST', body: JSON.stringify({ force }) }),
  adminExportSnapshot: () => request('/admin/export-snapshot'),
  adminExportPack: async () => {
    const res = await fetch(`${BASE}/admin/export-pack`)
    if (!res.ok) {
      let detail = ''
      try { detail = await res.text() } catch { /* ignore */ }
      throw new Error(detail || `导出失败 ${res.status}`)
    }
    return res.blob()
  },
  adminImportPack: async (file, force = true) => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/admin/import-pack?force=${force ? 'true' : 'false'}`, { method: 'POST', body: fd })
    if (!res.ok) {
      let detail = ''
      try {
        const data = await res.json()
        detail = data.detail?.message || data.detail || JSON.stringify(data)
      } catch {
        detail = await res.text()
      }
      throw new Error(detail || `导入失败 ${res.status}`)
    }
    return res.json()
  },
  analyzeQualFile: async (file) => {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch(`${BASE}/admin/qualifications/analyze-file`, { method: 'POST', body: fd })
    if (!res.ok) {
      let detail = ''
      try {
        const data = await res.json()
        detail = data.detail?.message || data.detail || JSON.stringify(data)
      } catch {
        detail = await res.text()
      }
      throw new Error(detail || `识别失败 ${res.status}`)
    }
    return res.json()
  },
  analyzeQualExisting: (id) => request(`/admin/qualifications/${id}/analyze`, { method: 'POST' }),
}
