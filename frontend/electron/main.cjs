const { app, BrowserWindow, shell, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const { spawn, exec } = require('child_process');

// Enforce single running instance of Urban Flow
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
  process.exit(0);
}

let mainWindow = null;
let splashWindow = null;
let backendProcess = null;
let frontendServer = null;
let isQuitting = false;

const BACKEND_PORT = 8000;
const FRONTEND_PORT = 5174;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

// Resolution of directories
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
const ICON_PATH = path.join(FRONTEND_DIR, 'public', 'urban-flow-dark.png');

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
  .lights {
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
  }
  .dot {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    animation: pulse 1.4s ease-in-out infinite alternate;
  }
  .red { background: #ef4444; box-shadow: 0 0 12px #ef4444aa; animation-delay: 0s; }
  .yellow { background: #f59e0b; box-shadow: 0 0 12px #f59e0baa; animation-delay: 0.25s; }
  .green { background: #10b981; box-shadow: 0 0 12px #10b981aa; animation-delay: 0.5s; }

  @keyframes pulse {
    0% { opacity: 0.4; transform: scale(0.9); }
    100% { opacity: 1; transform: scale(1.15); }
  }

  h1 {
    font-size: 24px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: #f5be28;
    margin-bottom: 4px;
  }
  p {
    font-size: 11px;
    font-weight: 600;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    margin-bottom: 24px;
  }
  .progress-wrap {
    width: 320px;
    height: 6px;
    background: #1c2128;
    border-radius: 6px;
    overflow: hidden;
    position: relative;
    border: 1px solid #30363d;
  }
  .progress-bar {
    position: absolute;
    top: 0; left: 0; bottom: 0;
    width: 45%;
    background: linear-gradient(90deg, #10b981, #f5be28, #ef4444);
    border-radius: 6px;
    animation: slide 1.4s ease-in-out infinite;
  }
  @keyframes slide {
    0% { left: -45%; width: 30%; }
    50% { width: 55%; }
    100% { left: 100%; width: 30%; }
  }
  .status {
    margin-top: 14px;
    font-size: 11px;
    color: #6e7681;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }
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
  <div class="progress-wrap">
    <div class="progress-bar"></div>
  </div>
  <div class="status">Starting local AI engine & signal planner...</div>
</body>
</html>`;

  splashWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(splashHtml));
}

function checkServerReady(url, timeoutMs = 25000, intervalMs = 300) {
  const startTime = Date.now();
  return new Promise((resolve) => {
    let done = false;
    const timer = setInterval(() => {
      if (Date.now() - startTime > timeoutMs) {
        clearInterval(timer);
        if (!done) {
          done = true;
          resolve(false);
        }
        return;
      }
      const req = http.get(url, (res) => {
        if (!done && res.statusCode < 500) {
          done = true;
          clearInterval(timer);
          resolve(true);
        }
      });
      req.on('error', () => {});
      req.setTimeout(800, () => req.destroy());
    }, intervalMs);
  });
}

function startBackend() {
  return new Promise((resolve) => {
    let launched = false;
    const launch = () => {
      if (launched) return;
      launched = true;
      console.log('[UrbanFlow Desktop] Launching background Python backend on port 8000...');
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
          ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)],
          {
            cwd: BACKEND_DIR,
            windowsHide: true,
            shell: false,
            stdio: stdioOption
          }
        );

        backendProcess.on('error', (err) => {
          console.error('[UrbanFlow Desktop] Failed to start backend:', err);
        });
      } catch (err) {
        console.error('[UrbanFlow Desktop] Spawn error for backend:', err);
      }

      checkServerReady(BACKEND_URL + '/api/health', 25000).then(() => {
        console.log('[UrbanFlow Desktop] Backend is ready.');
        resolve();
      });
    };

    const probe = http.get(BACKEND_URL + '/api/health', (res) => {
      if (res.statusCode === 200) {
        console.log('[UrbanFlow Desktop] Backend already active on port 8000.');
        return resolve();
      }
      launch();
    });

    probe.setTimeout(1200, () => {
      probe.destroy();
    });

    probe.on('error', () => {
      launch();
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

function startFrontend() {
  const clientDir = path.join(FRONTEND_DIR, 'dist', 'client');
  const indexHtmlPath = path.join(clientDir, 'index.html');

  return new Promise((resolve) => {
    frontendServer = http.createServer((req, res) => {
      try {
        const parsedUrl = new URL(req.url, FRONTEND_URL);
        const pathname = parsedUrl.pathname;

        // 1. Static file in dist/client
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

        // 2. Serve index.html (SPA entry)
        if (fs.existsSync(indexHtmlPath)) {
          res.writeHead(200, {
            'Content-Type': 'text/html; charset=utf-8',
            'Cache-Control': 'no-cache'
          });
          fs.createReadStream(indexHtmlPath).pipe(res);
          return;
        }

        res.writeHead(404);
        res.end('Not Found');
      } catch (err) {
        console.error('[UrbanFlow Desktop] Frontend request error:', err);
        res.writeHead(500);
        res.end('Internal Server Error: ' + err.message);
      }
    });

    frontendServer.on('error', (err) => {
      if (err.code === 'EADDRINUSE') {
        console.log('[UrbanFlow Desktop] Port 5174 already in use, assuming active.');
        resolve();
      } else {
        console.error('[UrbanFlow Desktop] Frontend server error:', err);
        resolve();
      }
    });

    frontendServer.listen(FRONTEND_PORT, '127.0.0.1', () => {
      console.log(`[UrbanFlow Desktop] Native frontend running at ${FRONTEND_URL}`);
      resolve();
    });
  });
}

function createWindow() {
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

  mainWindow.loadURL(FRONTEND_URL);

  const showMainWindow = () => {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.close();
      splashWindow = null;
    }
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show();
      mainWindow.focus();
    }
  };

  mainWindow.once('ready-to-show', showMainWindow);

  // Safety fallback: reveal window after 3.5 seconds maximum
  setTimeout(showMainWindow, 3500);

  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription) => {
    console.warn(`[UrbanFlow Desktop] Page failed to load (${errorCode}: ${errorDescription}), retrying in 1s...`);
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.loadURL(FRONTEND_URL);
      }
    }, 1000);
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function cleanupProcesses() {
  if (isQuitting) return;
  isQuitting = true;

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

app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }
});

app.whenReady().then(async () => {
  createSplash();
  try {
    await Promise.all([
      startBackend(),
      startFrontend()
    ]);
  } catch (err) {
    console.error('[UrbanFlow Desktop] Startup error:', err);
  }
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('before-quit', cleanupProcesses);
app.on('window-all-closed', () => {
  cleanupProcesses();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
