/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

const { contextBridge, ipcRenderer } = require('electron');

// Expose safe, typed desktop APIs to renderer via context bridge (R2 & SEC-RES-05)
// Master API token is NEVER exposed to renderer JavaScript context.
contextBridge.exposeInMainWorld('urbanflow', {
  isDesktop: true,
  platform: process.platform,
  invokeWorker: (action, data) => ipcRenderer.invoke('worker-request', { action, data }),
});
