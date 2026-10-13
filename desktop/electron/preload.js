const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("tenderAgentDesktop", {
  platform: process.platform,
  pickQualFolder: () => ipcRenderer.invoke("tender:pick-qual-folder"),
});
