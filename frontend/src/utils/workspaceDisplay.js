/** 工作台展示：项目工程目录文案（与后端 default_agent_workspace_root 语义一致） */
export const DEFAULT_WORKSPACE_LABEL = '默认目录'

export function formatProjectWorkspaceDir(project) {
  const dir = (project?.workspace_dir || '').trim()
  if (dir) return dir
  return DEFAULT_WORKSPACE_LABEL
}

export function workspaceDirTitle(project) {
  const dir = (project?.workspace_dir || '').trim()
  if (dir) return dir
  return '未单独指定时使用服务端 DATA_DIR/agent_workspace/default（含「过程资料」「产出」子目录）'
}
