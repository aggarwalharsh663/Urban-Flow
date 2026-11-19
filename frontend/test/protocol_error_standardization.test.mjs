/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const mainPath = path.join(__dirname, '..', 'electron', 'main.cjs');

console.log('--- Running Electron Protocol Error Standardization Tests (Issue #7) ---');

// Mock electron module before requiring main.cjs so Node test runner executes headlessly
const electronMock = {
  app: {
    name: 'Urban Flow',
    requestSingleInstanceLock: () => true,
    on: () => {},
    whenReady: () => new Promise(() => {}), // Don't trigger app lifecycle during unit tests
    quit: () => {},
    setAppUserModelId: () => {},
    setAboutPanelOptions: () => {},
  },
  BrowserWindow: class {
    constructor() {}
    loadURL() {}
    show() {}
    focus() {}
    isDestroyed() { return false; }
    close() {}
  },
  protocol: {
    registerSchemesAsPrivileged: () => {},
    handle: () => {},
  },
  shell: { openExternal: () => {} },
  net: {},
  ipcMain: { handle: () => {} },
  session: { defaultSession: null },
};

try {
  require.cache[require.resolve('electron')] = {
    id: require.resolve('electron'),
    filename: require.resolve('electron'),
    loaded: true,
    exports: electronMock,
  };
} catch (e) {
  // If electron module resolution fails directly, hook Module._load
  const Module = require('node:module');
  const origLoad = Module._load;
  Module._load = function (request, parent, isMain) {
    if (request === 'electron') return electronMock;
    return origLoad.apply(this, arguments);
  };
}

// Load exported functions from main.cjs
const {
  sanitizeErrorMessage,
  mapExceptionToStatus,
  createErrorResponse,
  applySecurityHeaders,
  isAllowedOrigin,
} = require(mainPath);

// Test 1: Canonical Error Schema Structure & JSON validity
const resp1 = createErrorResponse('Validation error: missing junction name', 400);
assert.equal(resp1.status, 400, 'HTTP status code must be preserved');
assert.equal(resp1.headers.get('content-type'), 'application/json; charset=utf-8');
assert.equal(resp1.headers.get('x-content-type-options'), 'nosniff');

await (async () => {
  const bodyText = await resp1.text();
  const json = JSON.parse(bodyText);
  assert.equal(json.ok, false, 'ok must be false');
  assert.equal(json.error, 'Validation error: missing junction name');
  assert.equal(json.detail, 'Validation error: missing junction name');
  console.log('✔ Test 1: Canonical Error Schema & JSON validity verified');
})();

// Test 2: Sanitization of Windows absolute paths
const winPathErr = 'Failed to load file at C:\\Users\\Administrator\\Desktop\\secret_video.mp4';
const sanitizedWin = sanitizeErrorMessage(winPathErr);
assert.equal(sanitizedWin.includes('C:\\Users\\Administrator'), false, 'Windows absolute paths must be redacted');
assert.equal(sanitizedWin.includes('secret_video.mp4'), true, 'Filename basename must be retained');
console.log('✔ Test 2: Windows absolute path disclosure prevention verified');

// Test 3: Sanitization of POSIX absolute paths while preserving API routes
const posixPathErr = 'ENOENT: /home/ubuntu/app/models/yolov8n.pt does not exist';
const sanitizedPosix = sanitizeErrorMessage(posixPathErr);
assert.equal(sanitizedPosix.includes('/home/ubuntu'), false, 'POSIX system paths must be redacted');
assert.equal(sanitizedPosix.includes('yolov8n.pt'), true, 'Model filename basename must be retained');

const apiRouteMsg = 'API route not found: GET /api/reports/123';
const sanitizedRoute = sanitizeErrorMessage(apiRouteMsg);
assert.equal(sanitizedRoute, 'API route not found: GET /api/reports/123', 'API routes must not be mutilated');
console.log('✔ Test 3: POSIX absolute path disclosure prevention & API route preservation verified');

// Test 4: Redaction of raw stack traces
const stackErr = 'Error: Worker crash\n    at Worker.process (C:\\UrbanFlow\\worker.js:12:34)\n    at emit (events.js:50:12)';
const sanitizedStack = sanitizeErrorMessage(stackErr);
assert.equal(sanitizedStack.includes('at Worker.process'), false, 'Stack trace lines must be stripped');
assert.equal(sanitizedStack.includes('events.js'), false, 'Stack trace filenames must be stripped');
assert.equal(sanitizedStack, 'Worker crash', 'Primary error description must be preserved');
console.log('✔ Test 4: Stack trace stripping verified');

// Test 5: Status code mapping
assert.equal(mapExceptionToStatus(new Error('Request timed out after 30000ms')), 504, 'Timeout maps to 504');
assert.equal(mapExceptionToStatus(new Error('Python worker is not running')), 503, 'Unavailable worker maps to 503');
assert.equal(mapExceptionToStatus(new Error('Unauthorized: invalid token')), 401, 'Unauthorized maps to 401');
assert.equal(mapExceptionToStatus(new Error('Forbidden: action requires scope')), 403, 'Forbidden scope maps to 403');
assert.equal(mapExceptionToStatus(new Error('Route not found')), 404, 'Not found maps to 404');
assert.equal(mapExceptionToStatus(new Error('Upload exceeds 100 MB limit')), 413, 'Upload limit maps to 413');
assert.equal(mapExceptionToStatus(new Error('Rate limit exceeded')), 429, 'Rate limit maps to 429');
assert.equal(mapExceptionToStatus(new Error('Request was cancelled')), 499, 'Cancellation maps to 499');
assert.equal(mapExceptionToStatus(new Error('Malformed JSON in request body')), 400, 'Malformed JSON maps to 400');
assert.equal(mapExceptionToStatus(new Error('Generic failure occurred')), 500, 'Unspecified exception maps to 500');
console.log('✔ Test 5: Exception to HTTP status mapping verified');

// Test 6: Safe fallback for empty or unexpected error values
assert.equal(sanitizeErrorMessage(''), 'The request could not be completed.');
assert.equal(sanitizeErrorMessage(null), 'The request could not be completed.');
assert.equal(sanitizeErrorMessage(undefined), 'The request could not be completed.');
assert.equal(sanitizeErrorMessage('[object Object]'), 'The request could not be completed.');
console.log('✔ Test 6: Empty, null, and [object Object] safe fallbacks verified');

// Test 7: Verify main.cjs protocol handler structure
const mainContent = fs.readFileSync(mainPath, 'utf-8');
assert.equal(mainContent.includes('createErrorResponse('), true, 'main.cjs must use centralized createErrorResponse');
assert.equal(mainContent.includes("API route not found:"), true, 'main.cjs must contain catch-all for unknown API routes');
assert.equal(mainContent.includes("rawPathname.startsWith('/api/')"), true, 'main.cjs must check unknown /api routes');
console.log('✔ Test 7: Centralized protocol handler error routing verified in main.cjs source');

console.log('--- ALL ELECTRON PROTOCOL ERROR TESTS PASSED ---');
process.exit(0);
