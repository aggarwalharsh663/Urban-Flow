const { app, BrowserWindow, shell, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const net = require('net');
const { spawn, exec } = require('child_process');

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
let backendProcess = null;
let frontendServer = null;
let isQuitting = false;

let BACKEND_PORT = 8008;
let FRONTEND_PORT = 5178;
let BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
let FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

// Directory paths
const FRONTEND_DIR = path.resolve(__dirname, '..');
const ROOT_DIR = path.resolve(FRONTEND_DIR, '..');
const BACKEND_DIR = path.join(ROOT_DIR, 'backend');

const candidatePythons = [
  path.join(BACKEND_DIR, 'python', 'python.exe'),
  path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe'),
  path.join(BACKEND_DIR, '.venv', 'python.exe'),
  path.join(BACKEND_DIR, 'python.exe'),
];
let PYTHON_EXE = candidatePythons.find((p) => fs.existsSync(p));
if (!PYTHON_EXE) {
  PYTHON_EXE = 'python';
}

const icoPath = path.join(FRONTEND_DIR, 'public', 'favicon.ico');
const pngPath = path.join(FRONTEND_DIR, 'public', 'urban-flow-dark.png');
const ICON_PATH = fs.existsSync(icoPath) ? icoPath : pngPath;

function checkPortFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => {
      server.close(() => resolve(true));
    });
    server.listen(port, '127.0.0.1');
  });
}

async function findAvailablePort(startPort, maxAttempts = 50) {
  for (let port = startPort; port < startPort + maxAttempts; port++) {
    const free = await checkPortFree(port);
    if (free) return port;
  }
  return startPort;
}

function createSplash() {
  log('Creating splash window...');
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
      contextIsolation: true
    }
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
  <div class="status">Starting local AI engine & signal planner...</div>
</body>
</html>`;

  splashWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(splashHtml));
}

function checkUrbanFlowReady(url, timeoutMs = 25000, intervalMs = 300) {
  const startTime = Date.now();
  return new Promise((resolve) => {
    let done = false;
    const timer = setInterval(() => {
      if (Date.now() - startTime > timeoutMs) {
        clearInterval(timer);
        if (!done) {
          done = true;
          log(`checkUrbanFlowReady timeout on ${url}`);
          resolve(false);
        }
        return;
      }
      const req = http.get(url, (res) => {
        let raw = '';
        res.on('data', (chunk) => { raw += chunk; });
        res.on('end', () => {
          if (!done && res.statusCode === 200) {
            try {
              const data = JSON.parse(raw);
              if (data.app === 'urban_flow' || data.computer_vision_ready !== undefined) {
                done = true;
                clearInterval(timer);
                log(`checkUrbanFlowReady verified Urban Flow backend (${res.statusCode}) on ${url}`);
                return resolve(true);
              }
            } catch (e) {}
          }
        });
      });
      req.on('error', () => {});
      req.setTimeout(800, () => req.destroy());
    }, intervalMs);
  });
}

async function startBackend() {
  BACKEND_PORT = await findAvailablePort(8008);
  BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
  log(`Resolved Urban Flow backend port: ${BACKEND_PORT}`);

  return new Promise((resolve) => {
    log('Launching background Python backend using:', PYTHON_EXE, 'on port', BACKEND_PORT);
    try {
      const logPath = path.join(BACKEND_DIR, 'backend.log');
      let stdioOption = 'ignore';
      try {
        const logFd = fs.openSync(logPath, 'a');
        stdioOption = ['ignore', logFd, logFd];
      } catch (e) {
        stdioOption = 'ignore';
      }

      backendProcess = spawn(
        PYTHON_EXE,
        ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT), '--app-dir', BACKEND_DIR],
        {
          cwd: BACKEND_DIR,
          windowsHide: true,
          shell: false,
          stdio: stdioOption,
          env: Object.assign({}, process.env, { PYTHONPATH: BACKEND_DIR })
        }
      );

      backendProcess.on('error', (err) => {
        log('Failed to spawn backend:', err);
      });
    } catch (err) {
      log('Spawn error for backend:', err);
    }

    checkUrbanFlowReady(BACKEND_URL + '/api/health', 25000).then(() => {
      log('Backend ready check completed.');
      resolve();
    });
  });
}

const mimeTypes = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.mp4': 'video/mp4',
};

function proxyRequest(req, res, targetUrl) {
  const parsedTarget = new URL(targetUrl);
  const options = {
    hostname: parsedTarget.hostname,
    port: parsedTarget.port,
    path: req.url,
    method: req.method,
    headers: { ...req.headers, host: `${parsedTarget.hostname}:${parsedTarget.port}` }
  };

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res);
  });

  proxyReq.on('error', (err) => {
    log('Proxy error:', err.message);
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ detail: 'Backend service unavailable on ' + targetUrl }));
  });

  req.pipe(proxyReq);
}

async function startFrontend() {
  FRONTEND_PORT = await findAvailablePort(5178);
  FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;
  log(`Resolved Urban Flow frontend port: ${FRONTEND_PORT}`);

  const clientDir = path.join(FRONTEND_DIR, 'dist', 'client');
  const indexHtmlPath = path.join(clientDir, 'index.html');
  const serverPath = path.join(FRONTEND_DIR, 'dist', 'server', 'server.js');

  return new Promise((resolve) => {
    frontendServer = http.createServer(async (req, res) => {
      try {
        const parsedUrl = new URL(req.url, FRONTEND_URL);
        const pathname = parsedUrl.pathname;

        // 1. Transparent API & uploads proxy to backend
        if (pathname.startsWith('/api') || pathname.startsWith('/uploads')) {
          return proxyRequest(req, res, BACKEND_URL);
        }

        // 2. Static file in dist/client
        if (pathname !== '/' && pathname !== '') {
          const filePath = path.join(clientDir, pathname);
          if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
            const ext = path.extname(filePath).toLowerCase();
            const contentType = mimeTypes[ext] || 'application/octet-stream';
            res.writeHead(200, {
              'Content-Type': contentType,
              'Cache-Control': 'public, max-age=31536000, immutable'
            });
            fs.createReadStream(filePath).pipe(res);
            return;
          }
        }

        // 3. Serve index.html (SPA entry)
        if (fs.existsSync(indexHtmlPath)) {
          res.writeHead(200, {
            'Content-Type': 'text/html; charset=utf-8',
            'Cache-Control': 'no-cache'
          });
          fs.createReadStream(indexHtmlPath).pipe(res);
          return;
        }

        // 4. Fallback: SSR if index.html is missing
        if (fs.existsSync(serverPath)) {
          try {
            const { pathToFileURL } = require('url');
            const mod = await import(pathToFileURL(serverPath).href);
            const handler = mod.default ?? mod;
            const fullUrl = `http://127.0.0.1:${FRONTEND_PORT}${req.url}`;
            const ssrRes = await handler.fetch(new Request(fullUrl));
            res.writeHead(ssrRes.status, Object.fromEntries(ssrRes.headers.entries()));
            const body = await ssrRes.text();
            res.end(body);
            return;
          } catch (e) {
            log('SSR fallback error:', e.message);
          }
        }

        res.writeHead(404);
        res.end('Not Found');
      } catch (err) {
        log('Frontend request error:', err);
        res.writeHead(500);
        res.end('Internal Server Error: ' + err.message);
      }
    });

    frontendServer.on('error', (err) => {
      log('Frontend server error:', err);
      resolve();
    });

    frontendServer.listen(FRONTEND_PORT, '127.0.0.1', () => {
      log(`Native frontend server running at ${FRONTEND_URL}`);
      resolve();
    });
  });
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
      spellcheck: false
    }
  });

  log('Loading frontend URL into mainWindow:', FRONTEND_URL);
  mainWindow.loadURL(FRONTEND_URL);

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
      }, 500);
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

  // Safety fallback: reveal window after 4 seconds
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
        mainWindow.loadURL(FRONTEND_URL);
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

  if (frontendServer) {
    try { frontendServer.close(); } catch (e) {}
    frontendServer = null;
  }

  if (backendProcess && backendProcess.pid) {
    if (process.platform === 'win32') {
      exec(`taskkill /pid ${backendProcess.pid} /T /F`, () => {});
    } else {
      backendProcess.kill('SIGTERM');
    }
    backendProcess = null;
  }
}

app.whenReady().then(async () => {
  log('app.whenReady() fired');
  createSplash();
  try {
    await Promise.all([
      startBackend(),
      startFrontend()
    ]);
  } catch (err) {
    log('Startup error in Promise.all:', err);
  }
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
