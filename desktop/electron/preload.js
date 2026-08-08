const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("tenderAgentDesktop", {
  platform: process.platform,
});
