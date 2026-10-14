/**
 * POST /projects/:id/sessions 返回 `{ session, project_id }`。
 * 向导进入「选择起点」时用它绑定 Copilot，不能把整包响应当成会话。
 */
export function sessionFromProjectBind(payload) {
  if (!payload || typeof payload !== 'object') return null
  const nested = payload.session
  if (nested && typeof nested === 'object' && nested.id != null && nested.id !== '') {
    return nested
  }
  return null
}
