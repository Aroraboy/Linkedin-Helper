/**
 * Preload script — exposes a safe API to the renderer process.
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  // App info
  isElectron: true,
  platform: process.platform,

  // Notify renderer that we're running in Electron
  getAppVersion: () => ipcRenderer.invoke("get-app-version"),
});
