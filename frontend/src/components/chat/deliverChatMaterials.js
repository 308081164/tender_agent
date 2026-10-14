/** 发送时才把已暂存的文件/文件夹交给现有上传接口。 */
export async function deliverChatMaterials(api, sessionId, staged) {
  const files = []
  for (const item of staged || []) {
    if (item.files?.length) files.push(...item.files)
    else if (item.file) files.push(item.file)
  }
  const folders = (staged || []).filter((item) => item.kind === 'folder' && item.path)
  const messages = []
  let workspace = null
  let session = null

  if (files.length) {
    const res = files.length === 1
      ? await api.uploadChatFile(sessionId, files[0])
      : await api.uploadChatFilesBatch(sessionId, files)
    if (res.user_message) messages.push(res.user_message)
    if (res.assistant_message) messages.push(res.assistant_message)
    workspace = res.workspace || res.session?.workspace || workspace
    session = res.session || session
  }

  for (const folder of folders) {
    const res = await api.importChatFolder(sessionId, folder.path, folder.label || '选择资质文件夹')
    if (res.user_message) messages.push(res.user_message)
    if (res.assistant_message) messages.push(res.assistant_message)
    workspace = res.workspace || res.session?.workspace || workspace
    session = res.session || session
  }

  return { messages, workspace, session }
}
