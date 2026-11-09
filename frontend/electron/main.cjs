const { app, BrowserWindow, protocol, shell, net, ipcMain, session } = require('electron');
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

// --- Security Limits & AllowLists ---
const MAX_UPLOAD_SIZE = 100 * 1024 * 1024; // 100 MB prototype limit
const ALLOWED_UPLOAD_EXTS = new Set(['.jpg', '.jpeg', '.png', '.mp4']);
const ALLOWED_CLIENT_EXTS = new Set([
  '.html', '.js', '.mjs', '.css', '.json',
  '.png', '.jpg', '.jpeg', '.svg', '.ico',
  '.woff', '.woff2', '.txt'
]);

// MIME types for safe asset serving
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
  '.txt': 'text/plain; charset=utf-8',
};

// Security Headers
const CSP_HEADER = (
  "default-src 'self' app:; " +
  "script-src 'self' app: 'unsafe-inline'; " +
  "style-src 'self' app: 'unsafe-inline' https://fonts.googleapis.com; " +
  "img-src 'self' app: data: blob:; " +
  "media-src 'self' app: blob:; " +
  "font-src 'self' app: data: https://fonts.gstatic.com; " +
  "connect-src 'self' app: http://127.0.0.1:8000; " +
  "frame-ancestors 'none';"
);

function applySecurityHeaders(headers = {}) {
  return Object.assign({
    'x-content-type-options': 'nosniff',
    'x-frame-options': 'DENY',
    'referrer-policy': 'strict-origin-when-cross-origin',
    'cross-origin-opener-policy': 'same-origin',
    'cross-origin-resource-policy': 'same-origin',
    'content-security-policy': CSP_HEADER,
  }, headers);
}

function isAllowedOrigin(urlStr) {
  try {
    const parsed = new URL(urlStr);
    return parsed.protocol === 'app:' && parsed.hostname === 'urbanflow';
  } catch {
    return false;
  }
}

// Anti-Path-Traversal containment validator (Finding 2)
function safeDecodeURI(uri) {
  let current = uri;
  for (let i = 0; i < 5; i++) {
    try {
      const decoded = decodeURIComponent(current);
      if (decoded === current) break;
      current = decoded;
    } catch (e) {
      return null; // Malformed URI encoding
    }
  }
  return current;
}

function resolveContainedPath(baseDir, requestedPath, allowedExtensions) {
  const decoded = safeDecodeURI(requestedPath);
  if (decoded === null) return null;
  // Reject null bytes, backslashes, control characters
  if (/[\0\x00-\x1f\\]/.test(decoded)) return null;

  // Normalize path
  const normalized = path.posix.normalize(decoded);
  // Ensure it doesn't escape via ..
  const parts = normalized.split('/').filter(p => p && p !== '.');
  if (parts.some(p => p === '..')) return null;

  const resolved = path.resolve(baseDir, parts.join(path.sep));
  const relative = path.relative(baseDir, resolved);

  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    return null; // Outside base directory
  }

  // Reject sensitive dotfiles and blacklisted extensions
  const baseName = path.basename(resolved).toLowerCase();
  if (baseName.startsWith('.') || baseName.endsWith('.env') || baseName.endsWith('.py') || baseName.endsWith('.pt') || baseName.endsWith('.lock') || baseName.endsWith('.cs') || baseName.endsWith('.bat') || baseName.endsWith('.vbs')) {
    return null;
  }

  const ext = path.extname(resolved).toLowerCase();
  if (allowedExtensions && !allowedExtensions.has(ext)) {
    return null; // Disallowed extension
  }

  return resolved;
}

// Magic bytes validator (Finding 4 & 7)
function verifyMagicBytes(buffer, ext) {
  if (!buffer || buffer.length < 4) return false;
  if (ext === '.jpg' || ext === '.jpeg') {
    return buffer[0] === 0xFF && buffer[1] === 0xD8 && buffer[2] === 0xFF;
  }
  if (ext === '.png') {
    return (
      buffer.length >= 8 &&
      buffer[0] === 0x89 && buffer[1] === 0x50 && buffer[2] === 0x4E && buffer[3] === 0x47 &&
      buffer[4] === 0x0D && buffer[5] === 0x0A && buffer[6] === 0x1A && buffer[7] === 0x0A
    );
  }
  if (ext === '.mp4') {
    return buffer.length >= 8 && buffer.slice(4, 8).toString('latin1') === 'ftyp';
  }
  return false;
}

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
        // Cooperative cancellation signal to worker process (R6)
        if (pythonProcess && !pythonProcess.killed) {
          try {
            pythonProcess.stdin.write(JSON.stringify({ id: crypto.randomUUID(), action: 'cancel', data: { cancel_id: reqId } }) + '\n');
          } catch (e) {}
        }
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

// Explicit Action Allowlist for IPC Worker Invocations (R2 & SEC-RES-05)
const ALLOWED_IPC_ACTIONS = new Set([
  'health',
  'simulate',
  'calculate-signal-plan',
  'analyse-image',
  'analyse-video',
  'get-report',
  'update-cycle',
  'update-counts',
  'cancel',
]);

// Secure IPC handlers for ContextBridge Preload (R2: Raw API token retrieval is completely eliminated)
if (ipcMain) {
  ipcMain.handle('worker-request', async (event, payload) => {
    const origin = event.senderFrame ? event.senderFrame.url : '';
    if (origin && !isAllowedOrigin(origin)) {
      log('Rejected IPC invocation from unauthorized origin:', origin);
      throw new Error('Unauthorized IPC sender origin');
    }
    const { action, data } = payload || {};
    if (!action || typeof action !== 'string' || !ALLOWED_IPC_ACTIONS.has(action)) {
      log('Rejected unapproved IPC action:', action);
      throw new Error('Forbidden or invalid IPC action: ' + action);
    }
    // Limit payload serialization size to 5 MB
    if (data && JSON.stringify(data).length > 5 * 1024 * 1024) {
      throw new Error('IPC request payload exceeds maximum limit of 5 MB.');
    }
    return sendIpcRequest(action, data || {});
  });
}

// --- Custom app:// Protocol Handler (Zero Network Ports) ---
function registerProtocolHandler() {
  protocol.handle('app', async (req) => {
    try {
      const parsedUrl = new URL(req.url);
      if (parsedUrl.hostname !== 'urbanflow') {
        log('Rejected unauthorized app host:', parsedUrl.hostname);
        return new Response('Forbidden Host', {
          status: 403,
          headers: applySecurityHeaders({ 'content-type': 'text/plain' }),
        });
      }
      let rawPathname = parsedUrl.pathname;
      log(`[app://] ${req.method} ${rawPathname}`);

      // 1. API: /api/health
      if (rawPathname === '/api/health') {
        const result = await sendIpcRequest('health', {});
        return new Response(JSON.stringify(result), {
          headers: applySecurityHeaders({ 'content-type': 'application/json' }),
        });
      }

      // 2. API: /api/simulate
      if (rawPathname === '/api/simulate' && req.method === 'POST') {
        const body = await req.json().catch(() => ({}));
        const result = await sendIpcRequest('simulate', body);
        return new Response(JSON.stringify(result), {
          headers: applySecurityHeaders({ 'content-type': 'application/json' }),
        });
      }

      // 3. API: /api/calculate-signal-plan
      if (rawPathname === '/api/calculate-signal-plan' && req.method === 'POST') {
        const body = await req.json().catch(() => ({}));
        const result = await sendIpcRequest('calculate-signal-plan', body);
        return new Response(JSON.stringify(result), {
          headers: applySecurityHeaders({ 'content-type': 'application/json' }),
        });
      }

      // 4. API: /api/reports/:id
      const reportMatch = rawPathname.match(/^\/api\/reports\/([a-zA-Z0-9]+)$/);
      if (reportMatch) {
        const reportId = reportMatch[1];
        const result = await sendIpcRequest('get-report', { report_id: reportId });
        return new Response(JSON.stringify(result), {
          headers: applySecurityHeaders({ 'content-type': 'application/json' }),
        });
      }

      // 5. API: /api/reports/:id/cycle
      const cycleMatch = rawPathname.match(/^\/api\/reports\/([a-zA-Z0-9]+)\/cycle$/);
      if (cycleMatch && req.method === 'PUT') {
        const reportId = cycleMatch[1];
        const body = await req.json().catch(() => ({}));
        const result = await sendIpcRequest('update-cycle', { report_id: reportId, ...body });
        return new Response(JSON.stringify(result), {
          headers: applySecurityHeaders({ 'content-type': 'application/json' }),
        });
      }

      // 6. API: /api/reports/:id/counts
      const countsMatch = rawPathname.match(/^\/api\/reports\/([a-zA-Z0-9]+)\/counts$/);
      if (countsMatch && req.method === 'PUT') {
        const reportId = countsMatch[1];
        const body = await req.json().catch(() => ({}));
        const result = await sendIpcRequest('update-counts', { report_id: reportId, ...body });
        return new Response(JSON.stringify(result), {
          headers: applySecurityHeaders({ 'content-type': 'application/json' }),
        });
      }

      // 7. API: /api/analyse-image and /api/analyse-video (multipart/form-data upload)
      if (rawPathname === '/api/analyse-image' || rawPathname === '/api/analyse-video') {
        const isVideo = rawPathname === '/api/analyse-video';
        const formData = await req.formData();
        const file = formData.get('file');
        if (!file) {
          return new Response(JSON.stringify({ detail: 'No file uploaded.' }), {
            status: 400,
            headers: applySecurityHeaders({ 'content-type': 'application/json' }),
          });
        }

        // Enforce 100 MB max size before reading into memory (Finding 4, 12)
        if (file.size > MAX_UPLOAD_SIZE) {
          return new Response(JSON.stringify({ detail: 'Upload exceeds 100 MB limit.' }), {
            status: 413,
            headers: applySecurityHeaders({ 'content-type': 'application/json' }),
          });
        }

        // Strict extension validation
        const ext = path.extname(file.name || '').toLowerCase();
        const expectedExts = isVideo ? new Set(['.mp4']) : new Set(['.jpg', '.jpeg', '.png']);
        if (!expectedExts.has(ext)) {
          return new Response(JSON.stringify({ detail: `Unsupported file type '${ext}'. Allowed: ${Array.from(expectedExts).join(', ')}` }), {
            status: 400,
            headers: applySecurityHeaders({ 'content-type': 'application/json' }),
          });
        }

        const tempName = `${crypto.randomUUID()}${ext}`;
        const tempPath = path.join(UPLOAD_DIR, tempName);
        const writeStream = fs.createWriteStream(tempPath);
        const reader = file.stream().getReader();

        let totalBytes = 0;
        let headerChunk = null;
        let streamFailed = false;

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const buf = Buffer.from(value);
            if (!headerChunk) {
              headerChunk = buf;
              if (!verifyMagicBytes(headerChunk, ext)) {
                streamFailed = true;
                break;
              }
            }
            totalBytes += buf.length;
            if (totalBytes > MAX_UPLOAD_SIZE) {
              streamFailed = true;
              break;
            }
            writeStream.write(buf);
          }
          await new Promise((res, rej) => {
            writeStream.end((err) => err ? rej(err) : res());
          });
        } catch (streamErr) {
          streamFailed = true;
        }

        if (streamFailed || !headerChunk || !verifyMagicBytes(headerChunk, ext)) {
          try { if (fs.existsSync(tempPath)) fs.unlinkSync(tempPath); } catch (e) {}
          if (totalBytes > MAX_UPLOAD_SIZE) {
            return new Response(JSON.stringify({ detail: 'Upload exceeds 100 MB limit.' }), {
              status: 413,
              headers: applySecurityHeaders({ 'content-type': 'application/json' }),
            });
          }
          return new Response(JSON.stringify({ detail: `File content does not match expected format for ${ext}.` }), {
            status: 400,
            headers: applySecurityHeaders({ 'content-type': 'application/json' }),
          });
        }

        try {
          const useCloudAi = formData.get('use_cloud_ai') === 'true';
          const result = await sendIpcRequest(isVideo ? 'analyse-video' : 'analyse-image', {
            file_path: tempPath,
            junction_name: (formData.get('junction_name') || '').trim() || null,
            green_budget: Math.max(40, Math.min(600, Number(formData.get('green_budget')) || 120)),
            yellow_seconds: Math.max(1, Math.min(10, Number(formData.get('yellow_seconds')) || 3)),
            use_cloud_ai: useCloudAi,
          }, isVideo ? 60000 : 30000);

          return new Response(JSON.stringify(result), {
            headers: applySecurityHeaders({ 'content-type': 'application/json' }),
          });
        } catch (ipcErr) {
          // Clean up temp file on failure
          try { if (fs.existsSync(tempPath)) fs.unlinkSync(tempPath); } catch (e) {}
          throw ipcErr;
        }
      }

      // 8. Static uploaded media files (/uploads/...) with traversal & XSS protection (Finding 2 & 4)
      if (rawPathname.startsWith('/uploads/')) {
        const uploadSubPath = rawPathname.substring('/uploads'.length);
        const safeFilePath = resolveContainedPath(UPLOAD_DIR, uploadSubPath, ALLOWED_UPLOAD_EXTS);
        if (safeFilePath && fs.existsSync(safeFilePath) && fs.statSync(safeFilePath).isFile()) {
          const ext = path.extname(safeFilePath).toLowerCase();
          const contentType = mimeTypes[ext] || 'application/octet-stream';
          const fileData = fs.readFileSync(safeFilePath);
          return new Response(fileData, {
            headers: {
              'content-type': contentType,
              'content-disposition': `inline; filename="${path.basename(safeFilePath)}"`,
              'x-content-type-options': 'nosniff',
              'content-security-policy': "default-src 'none'; sandbox",
              'cache-control': 'public, max-age=31536000, immutable',
            },
          });
        }
        return new Response('Not Found', {
          status: 404,
          headers: applySecurityHeaders({ 'content-type': 'text/plain' })
        });
      }

      // 9. Static frontend assets from dist/client with strict traversal protection (Finding 2)
      if (rawPathname !== '/' && rawPathname !== '' && rawPathname !== '/index.html') {
        const safeAssetPath = resolveContainedPath(CLIENT_DIR, rawPathname, ALLOWED_CLIENT_EXTS);
        if (safeAssetPath && fs.existsSync(safeAssetPath) && fs.statSync(safeAssetPath).isFile()) {
          const ext = path.extname(safeAssetPath).toLowerCase();
          const contentType = mimeTypes[ext] || 'application/octet-stream';
          const fileData = fs.readFileSync(safeAssetPath);
          return new Response(fileData, {
            headers: applySecurityHeaders({
              'content-type': contentType,
              'cache-control': 'public, max-age=31536000, immutable',
            }),
          });
        } else if (rawPathname.includes('..') || rawPathname.includes('%2e%2e') || rawPathname.includes('%252e')) {
          // Traversal attempt explicitly blocked
          return new Response('Forbidden', {
            status: 403,
            headers: applySecurityHeaders({ 'content-type': 'text/plain' })
          });
        }
      }

      // 10. Fallback: serve index.html (SPA entry)
      if (fs.existsSync(INDEX_HTML)) {
        const html = fs.readFileSync(INDEX_HTML, 'utf-8');
        return new Response(html, {
          headers: applySecurityHeaders({
            'content-type': 'text/html; charset=utf-8',
            'cache-control': 'no-cache',
          }),
        });
      }

      return new Response('Application bundle missing index.html.', {
        status: 500,
        headers: applySecurityHeaders({ 'content-type': 'text/plain' })
      });
    } catch (err) {
      log('[Protocol Error]', err);
      return new Response(JSON.stringify({ detail: err.message || 'Internal Error' }), {
        status: 500,
        headers: applySecurityHeaders({ 'content-type': 'application/json' }),
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
      sandbox: true,
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
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
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

  mainWindow.webContents.on('console-message', (event, level, message, line, sourceId) => {
    log(`[Renderer Console] ${message} (${sourceId}:${line})`);
  });

  mainWindow.webContents.on('render-process-gone', (event, details) => {
    log(`[Renderer Process Gone] reason: ${details.reason}, exitCode: ${details.exitCode}`);
  });

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

  // Navigation lock (Finding 9: Restrict navigation to approved origins)
  mainWindow.webContents.on('will-navigate', (event, navigationUrl) => {
    if (!isAllowedOrigin(navigationUrl)) {
      log('Prevented unauthorized navigation to:', navigationUrl);
      event.preventDefault();
    }
  });

  mainWindow.webContents.on('will-redirect', (event, navigationUrl) => {
    if (!isAllowedOrigin(navigationUrl)) {
      log('Prevented unauthorized redirect to:', navigationUrl);
      event.preventDefault();
    }
  });

  // Restrict window opening (Finding 9)
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const parsed = new URL(url);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        shell.openExternal(url);
      }
    } catch (e) {}
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

  // Prevent arbitrary webview attachment and enforce strict window opening policy
  if (session && session.defaultSession) {
    session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
      log('Blocked permission request for:', permission);
      callback(false);
    });
    session.defaultSession.setPermissionCheckHandler(() => false);
  }

  app.on('web-contents-created', (event, contents) => {
    contents.on('will-attach-webview', (e) => {
      e.preventDefault();
      log('Blocked unauthorized webview attachment.');
    });
    contents.setWindowOpenHandler(() => ({ action: 'deny' }));
    contents.on('will-navigate', (e, navUrl) => {
      if (!isAllowedOrigin(navUrl)) {
        e.preventDefault();
        log('Blocked web-contents navigation to:', navUrl);
      }
    });
    contents.on('will-redirect', (e, redUrl) => {
      if (!isAllowedOrigin(redUrl)) {
        e.preventDefault();
        log('Blocked web-contents redirect to:', redUrl);
      }
    });
  });

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
