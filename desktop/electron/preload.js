const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("tenderAgentDesktop", {
  platform: process.platform,
  pickQualFolder: () => ipcRenderer.invoke("tender:pick-qual-folder"),
  pickProjectWorkspaceDir: () => ipcRenderer.invoke("tender:pick-project-workspace"),
});
