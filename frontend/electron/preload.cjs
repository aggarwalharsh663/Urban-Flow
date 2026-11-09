const { contextBridge, ipcRenderer } = require('electron');

// Expose safe, typed desktop APIs to renderer via context bridge (R2 & SEC-RES-05)
// Master API token is NEVER exposed to renderer JavaScript context.
contextBridge.exposeInMainWorld('urbanflow', {
  isDesktop: true,
  platform: process.platform,
  invokeWorker: (action, data) => ipcRenderer.invoke('worker-request', { action, data }),
});
