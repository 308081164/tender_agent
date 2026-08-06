const BASE = '/api'

function buildQuery(params = {}) {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') sp.set(k, String(v))
  })
  const s = sp.toString()
  return s ? `?${s}` : ''
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    let detail = ''
    try {
      const data = await res.json()
      detail = data.detail?.message || data.detail || JSON.stringify(data)
    } catch {
      detail = await res.text()
    }
    throw new Error(detail || `请求失败 ${res.status}`)
  }
  if (res.status === 204) return null
  const type = res.headers.get('content-type') || ''
  if (type.includes('application/json')) return res.json()
  return res
}

export const api = {
  health: () => request('/health'),
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
  exportDoc: async (id) => {
    const res = await request(`/projects/${id}/export`)
    return res.blob()
  },
  listExports: (id) => request(`/projects/${id}/exports`),
  previewExport: (projectId, exportId) =>
    request(`/projects/${projectId}/exports/${exportId}/preview`),
  previewPdfUrl: (projectId, exportId) =>
    `${BASE}/projects/${projectId}/exports/${exportId}/preview.pdf`,
  downloadExportUrl: (projectId, exportId, inline = false) =>
    `${BASE}/projects/${projectId}/exports/${exportId}/download${inline ? '?inline=1' : ''}`,
  downloadExport: async (projectId, exportId) => {
    const res = await request(`/projects/${projectId}/exports/${exportId}/download`)
    return res.blob()
  },
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
  listChatMessages: (id) => request(`/chat/sessions/${id}/messages`),
  sendChatMessage: (sessionId, content) =>
    request(`/chat/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content }),
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
}
