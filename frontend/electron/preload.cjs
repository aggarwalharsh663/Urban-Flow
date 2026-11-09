const { contextBridge, ipcRenderer } = require('electron');

// Expose safe, typed desktop APIs to renderer via context bridge (SEC-RES-05)
contextBridge.exposeInMainWorld('urbanflow', {
  isDesktop: true,
  platform: process.platform,
  getApiToken: () => ipcRenderer.invoke('get-api-token'),
  invokeWorker: (action, data) => ipcRenderer.invoke('worker-request', { action, data }),
});
