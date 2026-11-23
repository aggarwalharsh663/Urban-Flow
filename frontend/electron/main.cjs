/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

const { app, BrowserWindow, protocol, shell, net, ipcMain, session, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const readline = require('readline');
const { spawn } = require('child_process');
const crypto = require('crypto');
const {
  TRUSTED_EXTERNAL_DOMAINS,
  isMatchingDomain,
  validateExternalUrl,
  openExternalUrl,
} = require('./url-utils.cjs');

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
  log('UNHANDLED REJECTION:', reason && reason.stack ? reason.stack : reason);
});

let mainWindow = null;
let splashWindow = null;
let pythonProcess = null;
let isQuitting = false;

app.name = 'Urban Flow';
try {
  const userDataPath = path.join(app.getPath('appData'), 'Urban Flow');
  app.setPath('userData', userDataPath);
  app.setAppUserModelId('Urban Flow');
  app.setAboutPanelOptions({
    applicationName: 'Urban Flow',
    applicationVersion: '1.0.0',
    copyright: 'Copyright © 2026 Harsh Aggarwal. All rights reserved.',
    authors: ['Harsh Aggarwal <aggarwalharsh663@gmail.com>'],
    website: 'https://github.com/aggarwalharsh663/Urban-Flow',
  });
} catch (e) {}

const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  log('Another instance is already running. Quitting duplicate instance immediately.');
  try { app.exit(0); } catch (e) {}
  process.exit(0);
} else {
  app.on('second-instance', () => {
    log('second-instance event received! Bringing mainWindow to front...');
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      if (!mainWindow.isVisible()) mainWindow.show();
      mainWindow.show();
      mainWindow.focus();
      try {
        mainWindow.setAlwaysOnTop(true);
        mainWindow.setAlwaysOnTop(false);
      } catch (e) {}
    } else if (splashWindow && !splashWindow.isDestroyed()) {
      if (splashWindow.isMinimized()) splashWindow.restore();
      splashWindow.show();
      splashWindow.focus();
    }
  });
}

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
  path.join(BACKEND_DIR, 'python', 'pythonw.exe'),
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
const ALLOWED_UPLOAD_EXTS = new Set(['.jpg', '.jpeg', '.png', '.mp4', '.avi']);
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
  '.avi': 'video/x-msvideo',
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

function resolveContainedPath(baseDir, requestedPath, allowedExtensions = null) {
  // Fail-closed if allowedExtensions is omitted, null, empty, or not a Set (Item 3)
  if (!allowedExtensions || !(allowedExtensions instanceof Set) || allowedExtensions.size === 0) {
    return null;
  }

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
  if (!allowedExtensions.has(ext)) {
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
  if (ext === '.avi') {
    return buffer.length >= 12 && buffer.slice(0, 4).toString('latin1') === 'RIFF' && buffer.slice(8, 12).toString('latin1') === 'AVI ';
  }
  return false;
}

/**
 * Write a buffer chunk to a writable stream honoring stream backpressure.
 * When the internal stream buffer is full (write() returns false), pauses reading
 * and awaits the 'drain' event or catches premature errors/closure.
 *
 * If the stream is already destroyed or closed on entry, rejects immediately.
 * Registers drain/close/error listeners BEFORE calling write() so that any
 * synchronous error emission from write() on a destroyed stream is captured.
 */
function writeChunkWithBackpressure(writeStream, chunk) {
  if (writeStream.destroyed || writeStream.closed) {
    return Promise.reject(new Error('Upload stream closed prematurely before drain.'));
  }

  // Register listeners BEFORE write() so that if the stream is destroyed
  // between our guard check and write() — causing an immediate 'error' or
  // 'close' event — we capture it rather than leaving it unhandled.
  return new Promise((resolve, reject) => {
    function onDrain() {
      cleanup();
      resolve();
    }
    function onClose() {
      cleanup();
      reject(new Error('Upload stream closed prematurely before drain.'));
    }
    function onError(err) {
      cleanup();
      reject(err);
    }

    function cleanup() {
      writeStream.removeListener('drain', onDrain);
      writeStream.removeListener('close', onClose);
      writeStream.removeListener('error', onError);
    }

    writeStream.once('drain', onDrain);
    writeStream.once('close', onClose);
    writeStream.once('error', onError);

    let needsDrain;
    try {
      needsDrain = !writeStream.write(chunk);
    } catch (syncErr) {
      // write() threw synchronously (some Node versions do this on destroyed streams)
      cleanup();
      reject(new Error('Upload stream closed prematurely before drain.'));
      return;
    }

    // If write() returned true the buffer accepted the chunk — no drain needed
    if (!needsDrain) {
      cleanup();
      resolve();
    }
    // else: needsDrain === true → wait for drain/close/error via registered listeners
  });
}

// --- Portless Python IPC Bridge (stdin / stdout pipes) ---
const pendingRequests = new Map();
let isWorkerReady = false;
let workerReadyResolve = null;
const workerReadyPromise = new Promise((resolve) => {
  workerReadyResolve = resolve;
});

// Session secret for authenticated Electron main <-> Python IPC worker communication (U-02)
const IPC_SESSION_TOKEN = crypto.randomBytes(32).toString('hex');

const ACTION_SCOPES = {
  'health': 'read',
  'copyright': 'read',
  'directions': 'read',
  'get-report': 'read',
  'simulate': 'reports:write',
  'calculate-signal-plan': 'reports:write',
  'signal-plan': 'reports:write',
  'update-cycle': 'reports:write',
  'update-counts': 'reports:write',
  'analyse-image': 'inference:write',
  'analyse-video': 'inference:write',
  'analyse-multi-video': 'inference:write',
  'cancel': 'admin',
};

// --- Canonical Error Response Helper (Issue #7) ---
function sanitizeErrorMessage(msg) {
  if (!msg) return 'The request could not be completed.';
  if (typeof msg !== 'string') {
    if (typeof msg === 'object' && msg !== null) {
      if (typeof msg.error === 'string' && msg.error.trim()) {
        msg = msg.error;
      } else if (typeof msg.detail === 'string' && msg.detail.trim()) {
        msg = msg.detail;
      } else if (typeof msg.message === 'string' && msg.message.trim()) {
        msg = msg.message;
      } else {
        try {
          msg = JSON.stringify(msg);
        } catch {
          msg = 'An unexpected error occurred.';
        }
      }
    } else {
      msg = String(msg);
    }
  }

  let clean = msg.trim();

  // Strip stack trace lines and keep only the primary error description line
  if (clean.includes('\n') || clean.includes('\r')) {
    clean = clean.split(/\r?\n/)[0].trim();
  }
  clean = clean.replace(/^Error:\s*/i, '').trim();

  // Strip control characters
  clean = clean.replace(/[\x00-\x08\x0b-\x1f]/g, '').trim();
  if (!clean || clean === '[object Object]') return 'The request could not be completed.';

  // Redact session secrets and tokens
  if (typeof IPC_SESSION_TOKEN !== 'undefined' && IPC_SESSION_TOKEN && clean.includes(IPC_SESSION_TOKEN)) {
    clean = clean.replaceAll(IPC_SESSION_TOKEN, '[REDACTED_TOKEN]');
  }

  // Redact local Windows absolute paths (e.g. C:\Users\... -> file.ext)
  clean = clean.replace(/[a-zA-Z]:\\(?:[^"'\s\n\r<>]+\\)+[^"'\s\n\r<>]*/g, (matched) => {
    return path.basename(matched) || '[path]';
  });

  // Redact POSIX system absolute paths (e.g. /home/..., /Users/... -> file.ext), preserving API routes like /api/...
  clean = clean.replace(/\/(?:home|Users|usr|var|tmp|etc|opt|root|proc)(?:\/[a-zA-Z0-9_.-]+)+/gi, (matched) => {
    return path.basename(matched) || '[path]';
  });

  return clean || 'The request could not be completed.';
}

function mapExceptionToStatus(err) {
  if (!err) return 500;
  const msg = (err.message || String(err)).toLowerCase();
  if (msg.includes('timed out') || msg.includes('timeout')) return 504;
  if (msg.includes('not running') || msg.includes('terminated') || msg.includes('unavailable') || msg.includes('initializing')) return 503;
  if (msg.includes('unauthorized') || msg.includes('invalid token') || msg.includes('missing token') || msg.includes('invalid ipc token')) return 401;
  if (msg.includes('forbidden') || msg.includes('insufficient scope') || msg.includes('unauthorized ipc sender') || msg.includes('unauthorized host')) return 403;
  if (msg.includes('not found') || msg.includes('unknown action') || msg.includes('unknown route')) return 404;
  if (msg.includes('exceeds') || msg.includes('too large') || msg.includes('payload exceeds')) return 413;
  if (msg.includes('rate limit') || msg.includes('too many requests')) return 429;
  if (msg.includes('cancelled') || msg.includes('canceled')) return 499;
  if (msg.includes('invalid') || msg.includes('unsupported') || msg.includes('malformed') || msg.includes('empty') || msg.includes('cannot be')) return 400;
  return 500;
}

function createErrorResponse(message, status = 400, extraHeaders = {}) {
  const safeMessage = sanitizeErrorMessage(message);
  const payload = {
    ok: false,
    error: safeMessage,
    detail: safeMessage,
  };
  return new Response(JSON.stringify(payload), {
    status,
    headers: applySecurityHeaders(Object.assign({
      'content-type': 'application/json; charset=utf-8',
    }, extraHeaders)),
  });
}

function startPythonWorker() {
  log('Spawning portless Python worker:', PYTHON_EXE, WORKER_SCRIPT);

  try {
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
          URBAN_FLOW_IPC_TOKEN: IPC_SESSION_TOKEN,
        }),
      }
    );
  } catch (err) {
    log('Fatal: synchronous exception during Python worker spawn:', err);
    if (dialog && typeof dialog.showErrorBox === 'function') {
      try {
        dialog.showErrorBox(
          'Urban Flow - Engine Startup Error',
          `Failed to launch backend engine (${PYTHON_EXE}).\n\nError: ${err.message}\n\nPlease verify that Windows Security or Smart App Control is not blocking Python binaries.`
        );
      } catch (e) {}
    }
    return;
  }

  if (!pythonProcess || !pythonProcess.stdout) {
    log('Fatal: Python worker spawn did not return a valid process.');
    return;
  }

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
    if (workerReadyResolve) workerReadyResolve();
    if (!isWorkerReady && dialog && typeof dialog.showErrorBox === 'function') {
      try {
        dialog.showErrorBox(
          'Urban Flow - Engine Startup Error',
          `Failed to initialize backend engine (${PYTHON_EXE}).\n\nError: ${err.message}\n\nPlease check Windows Security / Smart App Control settings.`
        );
      } catch (e) {}
    }
  });

  pythonProcess.on('exit', (code, signal) => {
    log(`Python process exited with code ${code}, signal ${signal}`);
    if (workerReadyResolve) workerReadyResolve();
    for (const [id, { reject }] of pendingRequests.entries()) {
      reject(new Error('Python worker terminated unexpectedly.'));
    }
    pendingRequests.clear();
  });
}

function sendIpcRequest(action, data = {}, timeoutMs = 30000, scope = null) {
  return new Promise((resolve, reject) => {
    const readyCheck = isWorkerReady
      ? Promise.resolve()
      : Promise.race([
          workerReadyPromise,
          new Promise((_, r) => setTimeout(() => r(new Error('Timed out waiting for Python worker to initialize.')), 15000)),
        ]);

    readyCheck
      .then(() => {
        if (!pythonProcess || pythonProcess.killed) {
          return reject(new Error('Python worker is not running.'));
        }

        const reqScope = scope || ACTION_SCOPES[action] || 'read';
        const reqId = crypto.randomUUID();
        const timer = setTimeout(() => {
          if (pendingRequests.has(reqId)) {
            pendingRequests.delete(reqId);
            // Cooperative cancellation signal to worker process (R6)
            if (pythonProcess && !pythonProcess.killed) {
              try {
                pythonProcess.stdin.write(JSON.stringify({
                  id: crypto.randomUUID(),
                  action: 'cancel',
                  token: IPC_SESSION_TOKEN,
                  scope: 'admin',
                  data: { cancel_id: reqId }
                }) + '\n');
              } catch (e) {}
            }
            reject(new Error(`Request '${action}' timed out after ${timeoutMs}ms.`));
          }
        }, timeoutMs);

        pendingRequests.set(reqId, {
          resolve: (res) => { clearTimeout(timer); resolve(res); },
          reject: (err) => { clearTimeout(timer); reject(err); },
        });

        const payload = JSON.stringify({
          id: reqId,
          action,
          token: IPC_SESSION_TOKEN,
          scope: reqScope,
          data
        }) + '\n';
        pythonProcess.stdin.write(payload, 'utf-8');
      })
      .catch((err) => {
        reject(err);
      });
  });
}

// Explicit Action Allowlist for IPC Worker Invocations (R2 & SEC-RES-05)
const ALLOWED_IPC_ACTIONS = new Set([
  'health',
  'copyright',
  'directions',
  'simulate',
  'calculate-signal-plan',
  'signal-plan',
  'analyse-image',
  'analyse-video',
  'analyse-multi-video',
  'get-report',
  'update-cycle',
  'update-counts',
  'cancel',
]);

// Secure IPC handlers for ContextBridge Preload (R2 & U-02: Scoped authorization enforced)
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
    const requiredScope = ACTION_SCOPES[action];
    if (!requiredScope) {
      log('Rejected IPC action without mapped scope:', action);
      throw new Error('Forbidden or invalid IPC action scope: ' + action);
    }
    // Limit payload serialization size to 5 MB
    if (data && JSON.stringify(data).length > 5 * 1024 * 1024) {
      throw new Error('IPC request payload exceeds maximum limit of 5 MB.');
    }
    const actionTimeout = action.startsWith('analyse') ? 180000 : (action === 'simulate' ? 60000 : 30000);
    return sendIpcRequest(action, data || {}, actionTimeout, requiredScope);
  });
}

// --- Custom app:// Protocol Handler (Zero Network Ports) ---
function registerProtocolHandler() {
  protocol.handle('app', async (req) => {
    try {
      const parsedUrl = new URL(req.url);
      if (parsedUrl.hostname !== 'urbanflow') {
        log('Rejected unauthorized app host:', parsedUrl.hostname);
        return createErrorResponse('Forbidden Host: unauthorized host origin.', 403);
      }
      let rawPathname = parsedUrl.pathname;
      log(`[app://] ${req.method} ${rawPathname}`);

      // 1. API: /api/health
      if (rawPathname === '/api/health') {
        try {
          const result = await sendIpcRequest('health', {}, 30000, 'read');
          return new Response(JSON.stringify(result), {
            headers: applySecurityHeaders({ 'content-type': 'application/json; charset=utf-8' }),
          });
        } catch (err) {
          return createErrorResponse(err.message || 'Failed to check system health.', mapExceptionToStatus(err));
        }
      }

      // 1a. API: /api/copyright
      if (rawPathname === '/api/copyright') {
        try {
          const result = await sendIpcRequest('copyright', {}, 30000, 'read');
          return new Response(JSON.stringify(result), {
            headers: applySecurityHeaders({ 'content-type': 'application/json; charset=utf-8' }),
          });
        } catch (err) {
          return createErrorResponse(err.message || 'Failed to verify copyright status.', mapExceptionToStatus(err));
        }
      }

      // 1b. API: /api/directions
      if (rawPathname === '/api/directions') {
        try {
          const result = await sendIpcRequest('directions', {}, 30000, 'read');
          return new Response(JSON.stringify(result), {
            headers: applySecurityHeaders({ 'content-type': 'application/json; charset=utf-8' }),
          });
        } catch (err) {
          return createErrorResponse(err.message || 'Failed to retrieve approach directions.', mapExceptionToStatus(err));
        }
      }

      // 2. API: /api/simulate
      if (rawPathname === '/api/simulate' && req.method === 'POST') {
        let body;
        try {
          body = await req.json();
        } catch {
          return createErrorResponse('Malformed JSON in request body.', 400);
        }
        try {
          const result = await sendIpcRequest('simulate', body || {}, 30000, 'reports:write');
          return new Response(JSON.stringify(result), {
            headers: applySecurityHeaders({ 'content-type': 'application/json; charset=utf-8' }),
          });
        } catch (err) {
          return createErrorResponse(err.message || 'Simulation execution failed.', mapExceptionToStatus(err));
        }
      }

      // 3. API: /api/calculate-signal-plan
      if (rawPathname === '/api/calculate-signal-plan' && req.method === 'POST') {
        let body;
        try {
          body = await req.json();
        } catch {
          return createErrorResponse('Malformed JSON in request body.', 400);
        }
        try {
          const result = await sendIpcRequest('calculate-signal-plan', body || {}, 30000, 'reports:write');
          return new Response(JSON.stringify(result), {
            headers: applySecurityHeaders({ 'content-type': 'application/json; charset=utf-8' }),
          });
        } catch (err) {
          return createErrorResponse(err.message || 'Signal plan calculation failed.', mapExceptionToStatus(err));
        }
      }

      // 4. API: /api/reports/:id
      const reportMatch = rawPathname.match(/^\/api\/reports\/([a-zA-Z0-9]+)$/);
      if (reportMatch) {
        const reportId = reportMatch[1];
        if (!reportId || reportId.trim().length === 0) {
          return createErrorResponse('Missing required parameter: report_id.', 400);
        }
        try {
          const result = await sendIpcRequest('get-report', { report_id: reportId }, 30000, 'read');
          return new Response(JSON.stringify(result), {
            headers: applySecurityHeaders({ 'content-type': 'application/json; charset=utf-8' }),
          });
        } catch (err) {
          return createErrorResponse(err.message || 'Failed to retrieve signal plan report.', mapExceptionToStatus(err));
        }
      }

      // 5. API: /api/reports/:id/cycle
      const cycleMatch = rawPathname.match(/^\/api\/reports\/([a-zA-Z0-9]+)\/cycle$/);
      if (cycleMatch && req.method === 'PUT') {
        const reportId = cycleMatch[1];
        let body;
        try {
          body = await req.json();
        } catch {
          return createErrorResponse('Malformed JSON in request body.', 400);
        }
        try {
          const result = await sendIpcRequest('update-cycle', { report_id: reportId, ...(body || {}) }, 30000, 'reports:write');
          return new Response(JSON.stringify(result), {
            headers: applySecurityHeaders({ 'content-type': 'application/json; charset=utf-8' }),
          });
        } catch (err) {
          return createErrorResponse(err.message || 'Failed to update cycle timing budget.', mapExceptionToStatus(err));
        }
      }

      // 6. API: /api/reports/:id/counts
      const countsMatch = rawPathname.match(/^\/api\/reports\/([a-zA-Z0-9]+)\/counts$/);
      if (countsMatch && req.method === 'PUT') {
        const reportId = countsMatch[1];
        let body;
        try {
          body = await req.json();
        } catch {
          return createErrorResponse('Malformed JSON in request body.', 400);
        }
        try {
          const result = await sendIpcRequest('update-counts', { report_id: reportId, ...(body || {}) }, 30000, 'reports:write');
          return new Response(JSON.stringify(result), {
            headers: applySecurityHeaders({ 'content-type': 'application/json; charset=utf-8' }),
          });
        } catch (err) {
          return createErrorResponse(err.message || 'Failed to update vehicle counts.', mapExceptionToStatus(err));
        }
      }

      // 7. API: /api/analyse-image and /api/analyse-video (multipart/form-data upload)
      if (rawPathname === '/api/analyse-image' || rawPathname === '/api/analyse-video') {
        const isVideo = rawPathname === '/api/analyse-video';
        let formData;
        try {
          formData = await req.formData();
        } catch {
          return createErrorResponse('Malformed multipart form-data in upload request.', 400);
        }
        const file = formData.get('file');
        if (!file || typeof file === 'string') {
          return createErrorResponse('No file uploaded.', 400);
        }

        // Enforce 100 MB max size before reading into memory (Finding 4, 12)
        if (file.size > MAX_UPLOAD_SIZE) {
          return createErrorResponse('Upload exceeds 100 MB limit.', 413);
        }

        // Strict extension validation
        const ext = path.extname(file.name || '').toLowerCase();
        const expectedExts = isVideo ? new Set(['.mp4', '.avi']) : new Set(['.jpg', '.jpeg', '.png']);
        if (!expectedExts.has(ext)) {
          return createErrorResponse(`Unsupported file type '${ext}'. Allowed: ${Array.from(expectedExts).join(', ')}`, 400);
        }

        const tempName = `${crypto.randomUUID()}${ext}`;
        const tempPath = path.join(UPLOAD_DIR, tempName);
        const writeStream = fs.createWriteStream(tempPath);
        const reader = file.stream().getReader();

        let totalBytes = 0;
        let headerChunk = null;
        let streamFailed = false;
        let streamError = null;

        writeStream.on('error', (err) => {
          streamError = streamError || err;
          streamFailed = true;
        });

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
            await writeChunkWithBackpressure(writeStream, buf);
          }

          if (streamFailed) {
            try { await reader.cancel(); } catch (e) {}
            writeStream.destroy();
          } else {
            await new Promise((res, rej) => {
              writeStream.end((err) => (err ? rej(err) : res()));
            });
          }
        } catch (streamErr) {
          streamFailed = true;
          streamError = streamErr;
          try { await reader.cancel(); } catch (e) {}
          if (!writeStream.destroyed) {
            writeStream.destroy(streamErr);
          }
        }

        if (streamFailed || !headerChunk || !verifyMagicBytes(headerChunk, ext)) {
          try { if (fs.existsSync(tempPath)) fs.unlinkSync(tempPath); } catch (e) {}
          if (totalBytes > MAX_UPLOAD_SIZE) {
            return createErrorResponse('Upload exceeds 100 MB limit.', 413);
          }
          if (streamError) {
            log('Upload stream error:', streamError.message || streamError);
          }
          return createErrorResponse(`File content does not match expected format for ${ext}.`, 400);
        }

        try {
          const useCloudAi = formData.get('use_cloud_ai') === 'true';
          const result = await sendIpcRequest(isVideo ? 'analyse-video' : 'analyse-image', {
            file_path: tempPath,
            junction_name: (formData.get('junction_name') || '').trim() || null,
            green_budget: Math.max(40, Math.min(600, Number(formData.get('green_budget')) || 120)),
            yellow_seconds: Math.max(1, Math.min(10, Number(formData.get('yellow_seconds')) || 3)),
            all_red_seconds: Math.max(0, Math.min(10, Number(formData.get('all_red_seconds')) || 0)),
            use_cloud_ai: useCloudAi,
          }, isVideo ? 60000 : 30000, 'inference:write');

          return new Response(JSON.stringify(result), {
            headers: applySecurityHeaders({ 'content-type': 'application/json; charset=utf-8' }),
          });
        } catch (ipcErr) {
          return createErrorResponse(ipcErr.message || 'Analysis processing failed.', mapExceptionToStatus(ipcErr));
        } finally {
          // Clean up temporary upload staging file now that Python worker has copied it to its managed destination
          try { if (fs.existsSync(tempPath)) fs.unlinkSync(tempPath); } catch (e) {}
        }
      }

      // 7b. API: /api/analyse-multi-video (directional 4-video upload)
      if (rawPathname === '/api/analyse-multi-video') {
        const MAX_VIDEO_UPLOAD_SIZE = 150 * 1024 * 1024; // 150 MB per video upload
        let formData;
        try {
          formData = await req.formData();
        } catch {
          return createErrorResponse('Malformed multipart form-data in upload request.', 400);
        }
        const directions = ['north', 'south', 'east', 'west'];
        const savedPaths = {};
        const createdFiles = [];

        try {
          for (const dir of directions) {
            const file = formData.get(`${dir}_file`) || formData.get(dir);
            if (!file || typeof file === 'string' || !file.name) continue;

            if (file.size > MAX_VIDEO_UPLOAD_SIZE) {
              return createErrorResponse(`Video for ${dir} exceeds 150 MB limit.`, 413);
            }

            const ext = path.extname(file.name || '').toLowerCase();
            const allowedExts = new Set(['.mp4', '.avi']);
            if (!allowedExts.has(ext)) {
              return createErrorResponse(`Unsupported video format '${ext}' for ${dir}. Allowed: .mp4, .avi`, 400);
            }

            const tempName = `${crypto.randomUUID()}${ext}`;
            const tempPath = path.join(UPLOAD_DIR, tempName);
            const writeStream = fs.createWriteStream(tempPath);
            const reader = file.stream().getReader();

            let totalBytes = 0;
            let headerChunk = null;
            let streamFailed = false;
            let streamError = null;

            writeStream.on('error', (err) => {
              streamError = streamError || err;
              streamFailed = true;
            });

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
                if (totalBytes > MAX_VIDEO_UPLOAD_SIZE) {
                  streamFailed = true;
                  break;
                }
                await writeChunkWithBackpressure(writeStream, buf);
              }

              if (streamFailed) {
                try { await reader.cancel(); } catch (e) {}
                writeStream.destroy();
              } else {
                await new Promise((res, rej) => {
                  writeStream.end((err) => (err ? rej(err) : res()));
                });
              }
            } catch (err) {
              streamFailed = true;
              streamError = err;
              try { await reader.cancel(); } catch (e) {}
              if (!writeStream.destroyed) {
                writeStream.destroy(err);
              }
            }

            if (streamFailed || !headerChunk || !verifyMagicBytes(headerChunk, ext)) {
              try { if (fs.existsSync(tempPath)) fs.unlinkSync(tempPath); } catch (e) {}
              if (totalBytes > MAX_VIDEO_UPLOAD_SIZE) {
                return createErrorResponse(`Video for ${dir} exceeds 150 MB limit.`, 413);
              }
              if (streamError) {
                log(`Upload stream error for ${dir}:`, streamError.message || streamError);
              }
              return createErrorResponse(`File content for ${dir} does not match expected format for ${ext}.`, 400);
            }

            savedPaths[dir] = tempPath;
            createdFiles.push(tempPath);
          }

          if (Object.keys(savedPaths).length === 0) {
            return createErrorResponse('At least one directional video must be uploaded.', 400);
          }

          const result = await sendIpcRequest('analyse-multi-video', {
            videos: savedPaths,
            junction_name: (formData.get('junction_name') || '').trim() || null,
            green_budget: Math.max(40, Math.min(600, Number(formData.get('green_budget')) || 120)),
            yellow_seconds: Math.max(1, Math.min(10, Number(formData.get('yellow_seconds')) || 3)),
            all_red_seconds: Math.max(0, Math.min(10, Number(formData.get('all_red_seconds')) || 0)),
            sample_fps: Math.max(0.5, Math.min(10, Number(formData.get('sample_fps')) || 2)),
          }, 180000, 'inference:write');

          return new Response(JSON.stringify(result), {
            headers: applySecurityHeaders({ 'content-type': 'application/json; charset=utf-8' }),
          });
        } catch (ipcErr) {
          return createErrorResponse(ipcErr.message || 'Multi-video analysis failed.', mapExceptionToStatus(ipcErr));
        } finally {
          // Clean up directional upload staging files now that Python worker has copied them to its managed destination
          for (const f of createdFiles) {
            try { if (fs.existsSync(f)) fs.unlinkSync(f); } catch (e) {}
          }
        }
      }

      // Catch-all for undefined /api routes (Requirement 4 & Test 11)
      if (rawPathname.startsWith('/api/')) {
        return createErrorResponse(`API route not found: ${req.method} ${rawPathname}`, 404);
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
      return createErrorResponse(err.message || 'Internal Server Error', mapExceptionToStatus(err));
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
      devTools: process.env.NODE_ENV === 'development',
    },
  });

  const appUrl = 'app://urbanflow/';

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

  // Block DevTools keyboard shortcuts in production
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (process.env.NODE_ENV !== 'development') {
      if (input.key === 'F12' || ((input.control || input.meta) && input.shift && input.key.toLowerCase() === 'i')) {
        event.preventDefault();
      }
    }
  });

  // Navigation lock (Finding 9: Restrict navigation to approved origins)
  mainWindow.webContents.on('will-navigate', (event, navigationUrl) => {
    if (!isAllowedOrigin(navigationUrl)) {
      log('Prevented unauthorized navigation to:', navigationUrl);
      event.preventDefault();
      // Safely handle external URL opening with validation and confirmation
      openExternalUrl(navigationUrl, { parentWindow: mainWindow, logger: log }).catch((err) => {
        log('Error in will-navigate external URL handling:', err && err.message ? err.message : err);
      });
    }
  });

  mainWindow.webContents.on('will-redirect', (event, navigationUrl) => {
    if (!isAllowedOrigin(navigationUrl)) {
      log('Prevented unauthorized redirect to:', navigationUrl);
      event.preventDefault();
    }
  });

  // Restrict window opening (Finding 9 & Navigation Security)
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    // Validate external URL and prompt confirmation for untrusted domains before opening.
    // Always deny renderer-created secondary windows to maintain single-window security model.
    openExternalUrl(url, { parentWindow: mainWindow, logger: log }).catch((err) => {
      log('Error in setWindowOpenHandler external URL handling:', err && err.message ? err.message : err);
    });
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    log('mainWindow closed');
    mainWindow = null;
  });

  log('Loading portless URL into mainWindow:', appUrl);
  mainWindow.loadURL(appUrl).catch((err) => {
    log('mainWindow.loadURL error:', err && err.stack ? err.stack : err);
  });
}

function cleanupProcesses() {
  if (isQuitting) return;
  isQuitting = true;
  log('cleanupProcesses() running...');

  if (pythonProcess && !pythonProcess.killed) {
    try {
      pythonProcess.kill();
    } catch (e) {}
    pythonProcess = null;
  }
}

app.whenReady().then(async () => {
  log('app.whenReady() fired - initializing portless engine...');
  createSplash();
  registerProtocolHandler();
  startPythonWorker();

  const timeoutPromise = new Promise((resolve) => setTimeout(resolve, 6000));
  await Promise.race([workerReadyPromise, timeoutPromise]).catch(() => {});
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
    contents.setWindowOpenHandler(({ url }) => {
      const win = BrowserWindow.fromWebContents(contents) || mainWindow;
      openExternalUrl(url, { parentWindow: win, logger: log }).catch(() => {});
      return { action: 'deny' };
    });
    contents.on('will-navigate', (e, navUrl) => {
      if (!isAllowedOrigin(navUrl)) {
        e.preventDefault();
        log('Blocked web-contents navigation to:', navUrl);
        const win = BrowserWindow.fromWebContents(contents) || mainWindow;
        openExternalUrl(navUrl, { parentWindow: win, logger: log }).catch(() => {});
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
  setTimeout(() => {
    try { app.exit(0); } catch (e) {}
    process.exit(0);
  }, 1000).unref();
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
    setTimeout(() => {
      try { app.exit(0); } catch (e) {}
      process.exit(0);
    }, 1000).unref();
  }
});

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    sanitizeErrorMessage,
    mapExceptionToStatus,
    createErrorResponse,
    applySecurityHeaders,
    isAllowedOrigin,
    resolveContainedPath,
    verifyMagicBytes,
    writeChunkWithBackpressure,
    sendIpcRequest,
    TRUSTED_EXTERNAL_DOMAINS,
    isMatchingDomain,
    validateExternalUrl,
    openExternalUrl,
  };
}
