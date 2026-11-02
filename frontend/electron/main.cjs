const { app, BrowserWindow, protocol, shell, net } = require('electron');
const path = require('path');
const fs = require('fs');
const readline = require('readline');
const { spawn } = require('child_process');
const crypto = require('crypto');

// Register custom scheme 'app' before ready
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'app',
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
      stream: true,
    },
  },
]);

const LOG_FILE = path.join(__dirname, 'electron.log');
function log(...args) {
  const msg = `[${new Date().toISOString()}] ${args.join(' ')}`;
  try { fs.appendFileSync(LOG_FILE, msg + '\n', 'utf-8'); } catch (e) {}
  console.log(msg);
}

process.on('uncaughtException', (err) => {
  log('UNCAUGHT EXCEPTION:', err && err.stack ? err.stack : err);
});
process.on('unhandledRejection', (reason) => {
  log('UNHANDLED REJECTION:', reason);
});

let mainWindow = null;
let splashWindow = null;
let pythonProcess = null;
let isQuitting = false;

const FRONTEND_DIR = path.resolve(__dirname, '..');
const ROOT_DIR = path.resolve(FRONTEND_DIR, '..');
const BACKEND_DIR = path.join(ROOT_DIR, 'backend');
const UPLOAD_DIR = path.join(BACKEND_DIR, 'uploads');
const CLIENT_DIR = path.join(FRONTEND_DIR, 'dist', 'client');
const INDEX_HTML = path.join(CLIENT_DIR, 'index.html');

if (!fs.existsSync(UPLOAD_DIR)) {
  fs.mkdirSync(UPLOAD_DIR, { recursive: true });
}

const candidatePythons = [
  path.join(BACKEND_DIR, 'python', 'python.exe'),
  path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe'),
  path.join(BACKEND_DIR, '.venv', 'python.exe'),
  path.join(BACKEND_DIR, 'python.exe'),
];
let PYTHON_EXE = candidatePythons.find((p) => fs.existsSync(p)) || 'python';
const WORKER_SCRIPT = path.join(BACKEND_DIR, 'ipc_worker.py');

const icoPath = path.join(FRONTEND_DIR, 'public', 'favicon.ico');
const pngPath = path.join(FRONTEND_DIR, 'public', 'urban-flow-dark.png');
const ICON_PATH = fs.existsSync(icoPath) ? icoPath : pngPath;

// --- Portless Python IPC Bridge (stdin / stdout pipes) ---
const pendingRequests = new Map();
let isWorkerReady = false;
let workerReadyResolve = null;
const workerReadyPromise = new Promise((resolve) => {
  workerReadyResolve = resolve;
});

function startPythonWorker() {
  log('Spawning portless Python worker:', PYTHON_EXE, WORKER_SCRIPT);

  pythonProcess = spawn(
    PYTHON_EXE,
    [WORKER_SCRIPT],
    {
      cwd: BACKEND_DIR,
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: Object.assign({}, process.env, {
        PYTHONPATH: BACKEND_DIR,
        PYTHONUNBUFFERED: '1',
      }),
    }
  );

  const rl = readline.createInterface({
    input: pythonProcess.stdout,
    crlfDelay: Infinity,
  });

  rl.on('line', (line) => {
    line = line.trim();
    if (!line) return;
    try {
      const msg = JSON.parse(line);
      if (msg.event === 'ready') {
        log('Python worker is READY (Portless IPC established).');
        isWorkerReady = true;
        if (workerReadyResolve) workerReadyResolve();
        return;
      }

      const reqId = msg.id;
      if (reqId && pendingRequests.has(reqId)) {
        const { resolve, reject } = pendingRequests.get(reqId);
        pendingRequests.delete(reqId);
        if (msg.ok) {
          resolve(msg.result);
        } else {
          reject(new Error(msg.error || 'Worker request failed.'));
        }
      }
    } catch (e) {
      log('Worker stdout parse error:', e.message, line);
    }
  });

  pythonProcess.stderr.on('data', (data) => {
    log('[Python stderr]', data.toString().trim());
  });

  pythonProcess.on('error', (err) => {
    log('Python process spawn error:', err);
  });

  pythonProcess.on('exit', (code, signal) => {
    log(`Python process exited with code ${code}, signal ${signal}`);
    for (const [id, { reject }] of pendingRequests.entries()) {
      reject(new Error('Python worker terminated unexpectedly.'));
    }
    pendingRequests.clear();
  });
}

function sendIpcRequest(action, data = {}, timeoutMs = 30000) {
  return new Promise(async (resolve, reject) => {
    if (!isWorkerReady) {
      await Promise.race([
        workerReadyPromise,
        new Promise((_, r) => setTimeout(() => r(new Error('Timed out waiting for Python worker to initialize.')), 15000)),
      ]);
    }

    if (!pythonProcess || pythonProcess.killed) {
      return reject(new Error('Python worker is not running.'));
    }

    const reqId = crypto.randomUUID();
    const timer = setTimeout(() => {
      if (pendingRequests.has(reqId)) {
        pendingRequests.delete(reqId);
        reject(new Error(`Request '${action}' timed out after ${timeoutMs}ms.`));
      }
    }, timeoutMs);

    pendingRequests.set(reqId, {
      resolve: (res) => { clearTimeout(timer); resolve(res); },
      reject: (err) => { clearTimeout(timer); reject(err); },
    });

    const payload = JSON.stringify({ id: reqId, action, data }) + '\n';
    pythonProcess.stdin.write(payload, 'utf-8');
  });
}

// --- MIME types for file serving ---
const mimeTypes = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.mp4': 'video/mp4',
};

// --- Custom app:// Protocol Handler (Zero Network Ports) ---
function registerProtocolHandler() {
  protocol.handle('app', async (req) => {
    try {
      const parsedUrl = new URL(req.url);
      let pathname = decodeURIComponent(parsedUrl.pathname);
      log(`[app://] ${req.method} ${pathname}`);

      // 1. API: /api/health
      if (pathname === '/api/health') {
        const result = await sendIpcRequest('health', {});
        return new Response(JSON.stringify(result), {
          headers: { 'content-type': 'application/json' },
        });
      }

      // 2. API: /api/simulate
      if (pathname === '/api/simulate' && req.method === 'POST') {
        const body = await req.json().catch(() => ({}));
        const result = await sendIpcRequest('simulate', body);
        return new Response(JSON.stringify(result), {
          headers: { 'content-type': 'application/json' },
        });
      }

      // 3. API: /api/calculate-signal-plan
      if (pathname === '/api/calculate-signal-plan' && req.method === 'POST') {
        const body = await req.json().catch(() => ({}));
        const result = await sendIpcRequest('calculate-signal-plan', body);
        return new Response(JSON.stringify(result), {
          headers: { 'content-type': 'application/json' },
        });
      }

      // 4. API: /api/reports/:id
      const reportMatch = pathname.match(/^\/api\/reports\/([a-zA-Z0-9]+)$/);
      if (reportMatch) {
        const reportId = reportMatch[1];
        const result = await sendIpcRequest('get-report', { report_id: reportId });
        return new Response(JSON.stringify(result), {
          headers: { 'content-type': 'application/json' },
        });
      }

      // 5. API: /api/reports/:id/cycle
      const cycleMatch = pathname.match(/^\/api\/reports\/([a-zA-Z0-9]+)\/cycle$/);
      if (cycleMatch && req.method === 'PUT') {
        const reportId = cycleMatch[1];
        const body = await req.json().catch(() => ({}));
        const result = await sendIpcRequest('update-cycle', { report_id: reportId, ...body });
        return new Response(JSON.stringify(result), {
          headers: { 'content-type': 'application/json' },
        });
      }

      // 6. API: /api/reports/:id/counts
      const countsMatch = pathname.match(/^\/api\/reports\/([a-zA-Z0-9]+)\/counts$/);
      if (countsMatch && req.method === 'PUT') {
        const reportId = countsMatch[1];
        const body = await req.json().catch(() => ({}));
        const result = await sendIpcRequest('update-counts', { report_id: reportId, ...body });
        return new Response(JSON.stringify(result), {
          headers: { 'content-type': 'application/json' },
        });
      }

      // 7. API: /api/analyse-image and /api/analyse-video (multipart/form-data upload)
      if (pathname === '/api/analyse-image' || pathname === '/api/analyse-video') {
        const isVideo = pathname === '/api/analyse-video';
        const formData = await req.formData();
        const file = formData.get('file');
        if (!file) {
          return new Response(JSON.stringify({ detail: 'No file uploaded.' }), {
            status: 400,
            headers: { 'content-type': 'application/json' },
          });
        }

        const ext = path.extname(file.name || (isVideo ? '.mp4' : '.jpg')).toLowerCase();
        const tempName = `${crypto.randomUUID()}${ext}`;
        const tempPath = path.join(UPLOAD_DIR, tempName);

        const arrayBuffer = await file.arrayBuffer();
        fs.writeFileSync(tempPath, Buffer.from(arrayBuffer));

        const result = await sendIpcRequest(isVideo ? 'analyse-video' : 'analyse-image', {
          file_path: tempPath,
          junction_name: formData.get('junction_name') || null,
          green_budget: Number(formData.get('green_budget')) || 120,
          yellow_seconds: Number(formData.get('yellow_seconds')) || 3,
        });

        return new Response(JSON.stringify(result), {
          headers: { 'content-type': 'application/json' },
        });
      }

      // 8. Static uploaded media files (/uploads/...)
      if (pathname.startsWith('/uploads/')) {
        const filename = path.basename(pathname);
        const filePath = path.join(UPLOAD_DIR, filename);
        if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
          const ext = path.extname(filePath).toLowerCase();
          const contentType = mimeTypes[ext] || 'application/octet-stream';
          const fileData = fs.readFileSync(filePath);
          return new Response(fileData, {
            headers: {
              'content-type': contentType,
              'cache-control': 'public, max-age=31536000, immutable',
            },
          });
        }
        return new Response('Not Found', { status: 404 });
      }

      // 9. Static frontend assets from dist/client
      if (pathname !== '/' && pathname !== '' && pathname !== '/index.html') {
        const filePath = path.join(CLIENT_DIR, pathname);
        if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
          const ext = path.extname(filePath).toLowerCase();
          const contentType = mimeTypes[ext] || 'application/octet-stream';
          const fileData = fs.readFileSync(filePath);
          return new Response(fileData, {
            headers: {
              'content-type': contentType,
              'cache-control': 'public, max-age=31536000, immutable',
            },
          });
        }
      }

      // 10. Fallback: serve index.html (SPA entry)
      if (fs.existsSync(INDEX_HTML)) {
        const html = fs.readFileSync(INDEX_HTML, 'utf-8');
        return new Response(html, {
          headers: {
            'content-type': 'text/html; charset=utf-8',
            'cache-control': 'no-cache',
          },
        });
      }

      return new Response('Application bundle missing index.html.', { status: 500 });
    } catch (err) {
      log('[Protocol Error]', err);
      return new Response(JSON.stringify({ detail: err.message || 'Internal Error' }), {
        status: 500,
        headers: { 'content-type': 'application/json' },
      });
    }
  });
}

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 460,
    height: 300,
    frame: false,
    resizable: false,
    center: true,
    show: true,
    alwaysOnTop: true,
    backgroundColor: '#0c0e12',
    icon: ICON_PATH,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  const splashHtml = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; }
  body {
    background: #0c0e12;
    color: #f0f2f5;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    border: 2px solid #232833;
    border-radius: 12px;
    overflow: hidden;
    position: relative;
  }
  .lights { display: flex; gap: 12px; margin-bottom: 16px; }
  .dot { width: 14px; height: 14px; border-radius: 50%; animation: pulse 1.4s ease-in-out infinite alternate; }
  .red { background: #ef4444; box-shadow: 0 0 12px #ef4444aa; animation-delay: 0s; }
  .yellow { background: #f59e0b; box-shadow: 0 0 12px #f59e0baa; animation-delay: 0.25s; }
  .green { background: #10b981; box-shadow: 0 0 12px #10b981aa; animation-delay: 0.5s; }

  @keyframes pulse {
    0% { opacity: 0.4; transform: scale(0.9); }
    100% { opacity: 1; transform: scale(1.15); }
  }

  h1 { font-size: 24px; font-weight: 700; letter-spacing: 0.5px; color: #f5be28; margin-bottom: 4px; }
  p { font-size: 11px; font-weight: 600; color: #8b949e; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 24px; }
  .progress-wrap { width: 320px; height: 6px; background: #1c2128; border-radius: 6px; overflow: hidden; position: relative; border: 1px solid #30363d; }
  .progress-bar { position: absolute; top: 0; left: 0; bottom: 0; width: 45%; background: linear-gradient(90deg, #10b981, #f5be28, #ef4444); border-radius: 6px; animation: slide 1.4s ease-in-out infinite; }
  @keyframes slide {
    0% { left: -45%; width: 30%; }
    50% { width: 55%; }
    100% { left: 100%; width: 30%; }
  }
  .status { margin-top: 14px; font-size: 11px; color: #6e7681; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
</style>
</head>
<body>
  <div class="lights">
    <div class="dot red"></div>
    <div class="dot yellow"></div>
    <div class="dot green"></div>
  </div>
  <h1>Urban Flow</h1>
  <p>Adaptive Traffic Signal System</p>
  <div class="progress-wrap"><div class="progress-bar"></div></div>
  <div class="status">Starting local AI engine & signal planner (Portless)...</div>
</body>
</html>`;

  splashWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(splashHtml));
}

function createWindow() {
  log('createWindow() called');
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1080,
    minHeight: 720,
    title: 'Urban Flow - Adaptive Traffic Signal System',
    backgroundColor: '#0c0e12',
    icon: ICON_PATH,
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      spellcheck: false,
    },
  });

  const appUrl = 'app://urbanflow/';
  log('Loading portless URL into mainWindow:', appUrl);
  mainWindow.loadURL(appUrl);

  let isMainShown = false;
  const showMainWindow = () => {
    if (isMainShown) return;
    isMainShown = true;
    log('showMainWindow executing...');

    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show();
      mainWindow.focus();
      log('mainWindow is now VISIBLE and focused.');
    }

    if (splashWindow && !splashWindow.isDestroyed()) {
      setTimeout(() => {
        try {
          if (splashWindow && !splashWindow.isDestroyed()) {
            splashWindow.close();
            splashWindow = null;
            log('splashWindow closed smoothly.');
          }
        } catch (e) {}
      }, 400);
    }
  };

  mainWindow.once('ready-to-show', () => {
    log('mainWindow ready-to-show event fired!');
    showMainWindow();
  });

  mainWindow.webContents.on('did-finish-load', () => {
    log('mainWindow webContents did-finish-load!');
    showMainWindow();
  });

  setTimeout(() => {
    if (!isMainShown) {
      log('Fallback timer: showing mainWindow');
      showMainWindow();
    }
  }, 4000);

  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription) => {
    log(`mainWindow did-fail-load: ${errorCode} ${errorDescription}`);
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.loadURL(appUrl);
      }
    }, 1500);
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    log('mainWindow closed');
    mainWindow = null;
  });
}

function cleanupProcesses() {
  if (isQuitting) return;
  isQuitting = true;
  log('cleanupProcesses() running...');

  if (pythonProcess && !pythonProcess.killed) {
    try {
      pythonProcess.kill('SIGTERM');
    } catch (e) {}
    pythonProcess = null;
  }
}

app.whenReady().then(async () => {
  log('app.whenReady() fired - initializing portless engine...');
  createSplash();
  registerProtocolHandler();
  startPythonWorker();

  await workerReadyPromise.catch(() => {});
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('before-quit', () => {
  log('before-quit event');
  cleanupProcesses();
});

app.on('window-all-closed', () => {
  log('window-all-closed event');
  if (mainWindow && !mainWindow.isDestroyed()) {
    log('Ignoring window-all-closed because mainWindow still exists.');
    return;
  }
  cleanupProcesses();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
