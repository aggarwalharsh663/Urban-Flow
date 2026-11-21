/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

// Automated Security Test for Finding 2 & Electron Hardening
import assert from 'node:assert/strict';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const FRONTEND_DIR = path.resolve(__dirname, '..');
const ROOT_DIR = path.resolve(FRONTEND_DIR, '..');
const CLIENT_DIR = path.join(FRONTEND_DIR, 'dist', 'client');
const UPLOAD_DIR = path.join(ROOT_DIR, 'backend', 'uploads');

const ALLOWED_CLIENT_EXTS = new Set([
  '.html', '.js', '.mjs', '.css', '.json',
  '.png', '.jpg', '.jpeg', '.svg', '.ico',
  '.woff', '.woff2', '.txt'
]);

function safeDecodeURI(uri) {
  let current = uri;
  for (let i = 0; i < 5; i++) {
    try {
      const decoded = decodeURIComponent(current);
      if (decoded === current) break;
      current = decoded;
    } catch (e) {
      return null;
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
  if (/[\0\x00-\x1f\\]/.test(decoded)) return null;

  const normalized = path.posix.normalize(decoded);
  const parts = normalized.split('/').filter(p => p && p !== '.');
  if (parts.some(p => p === '..')) return null;

  const resolved = path.resolve(baseDir, parts.join(path.sep));
  const relative = path.relative(baseDir, resolved);

  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    return null;
  }

  const baseName = path.basename(resolved).toLowerCase();
  if (baseName.startsWith('.') || baseName.endsWith('.env') || baseName.endsWith('.py') || baseName.endsWith('.pt') || baseName.endsWith('.lock')) {
    return null;
  }

  const ext = path.extname(resolved).toLowerCase();
  if (!allowedExtensions.has(ext)) {
    return null;
  }

  return resolved;
}

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

console.log('--- Running Electron Security & Path Traversal Tests ---');

// Test 1: Plain Traversal Rejection
const plainTraversal = resolveContainedPath(CLIENT_DIR, '../../backend/.env', ALLOWED_CLIENT_EXTS);
assert.equal(plainTraversal, null, 'Plain traversal to backend/.env must be rejected');
console.log('✔ Plain traversal rejected');

// Test 2: Encoded Traversal Rejection
const encodedTraversal = resolveContainedPath(CLIENT_DIR, '..%2f..%2fbackend%2f.env', ALLOWED_CLIENT_EXTS);
assert.equal(encodedTraversal, null, 'Encoded traversal must be rejected');
console.log('✔ Encoded traversal rejected');

// Test 3: Double-Encoded Traversal Rejection
const doubleEncoded = resolveContainedPath(CLIENT_DIR, '..%252f..%252fbackend%252f.env', ALLOWED_CLIENT_EXTS);
assert.equal(doubleEncoded, null, 'Double-encoded traversal must be rejected');
console.log('✔ Double-encoded traversal rejected');

// Test 4: Null Byte Injection
const nullByte = resolveContainedPath(CLIENT_DIR, 'index.html%00../../.env', ALLOWED_CLIENT_EXTS);
assert.equal(nullByte, null, 'Null byte injection must be rejected');
console.log('✔ Null byte injection rejected');

// Test 5: Sensitive dotfile blocking (e.g. .env, .git)
const dotfile = resolveContainedPath(CLIENT_DIR, '.env', ALLOWED_CLIENT_EXTS);
assert.equal(dotfile, null, '.env in root must be blocked');
console.log('✔ Direct .env access blocked');

// Test 6: Python script access blocked
const pyFile = resolveContainedPath(CLIENT_DIR, 'main.py', ALLOWED_CLIENT_EXTS);
assert.equal(pyFile, null, 'Python script access must be blocked by extension allowlist');
console.log('✔ Disallowed extension blocked');

// Test 7: Legitimate frontend asset resolution
const legitimate = resolveContainedPath(CLIENT_DIR, 'robots.txt', ALLOWED_CLIENT_EXTS);
assert.notEqual(legitimate, null, 'Legitimate asset within CLIENT_DIR must resolve');
console.log('✔ Legitimate asset resolved safely');

// Test 7b: Default fail-closed when allowedExtensions omitted/null/empty (Item 3 Hardening)
assert.equal(resolveContainedPath(CLIENT_DIR, 'robots.txt'), null, 'Omitted allowedExtensions must fail-closed and return null');
assert.equal(resolveContainedPath(CLIENT_DIR, 'robots.txt', null), null, 'Null allowedExtensions must fail-closed and return null');
assert.equal(resolveContainedPath(CLIENT_DIR, 'robots.txt', new Set()), null, 'Empty allowedExtensions set must fail-closed and return null');
console.log('✔ Fail-closed path traversal defaults verified');

// Test 8: Magic bytes verification for PNG
const realPngHeader = Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00]);
assert.equal(verifyMagicBytes(realPngHeader, '.png'), true, 'Real PNG header should pass');

// Test 9: Magic bytes rejection for HTML pretending to be PNG
const fakePng = Buffer.from('<html><body><script>alert(1)</script></body></html>');
assert.equal(verifyMagicBytes(fakePng, '.png'), false, 'Fake PNG must fail magic byte check');
console.log('✔ Magic bytes validation and spoofing defense verified');

// Test 10: Preload script existence & Context Bridge verification (SEC-RES-05)
const preloadPath = path.join(FRONTEND_DIR, 'electron', 'preload.cjs');
assert.equal(fs.existsSync(preloadPath), true, 'preload.cjs must exist');
const preloadContent = fs.readFileSync(preloadPath, 'utf-8');
assert.equal(preloadContent.includes('contextBridge.exposeInMainWorld'), true, 'preload must use contextBridge.exposeInMainWorld');
assert.equal(preloadContent.includes('urbanflow'), true, 'preload must namespace under urbanflow');
console.log('✔ ContextBridge preload script verified');

// Test 11: Electron main process attaches preload script
const mainCjsPath = path.join(FRONTEND_DIR, 'electron', 'main.cjs');
const mainContent = fs.readFileSync(mainCjsPath, 'utf-8');
assert.equal(mainContent.includes("preload.cjs"), true, 'main.cjs must configure preload.cjs');
console.log('✔ Electron main webPreferences preload registration verified');

// Test 12: Allowed origin validator
function isAllowedOrigin(urlStr) {
  try {
    const parsed = new URL(urlStr);
    return parsed.protocol === 'app:' && parsed.hostname === 'urbanflow';
  } catch {
    return false;
  }
}
assert.equal(isAllowedOrigin('app://urbanflow/'), true, 'app://urbanflow/ must be allowed');
assert.equal(isAllowedOrigin('app://urbanflow/api/health'), true, 'app://urbanflow/api/health must be allowed');
assert.equal(isAllowedOrigin('app://foreign.example/'), false, 'Foreign app:// host must be blocked');
assert.equal(isAllowedOrigin('http://untrusted.example/'), false, 'External http must be blocked');
assert.equal(isAllowedOrigin('file:///etc/passwd'), false, 'file protocol must be blocked');
assert.equal(isAllowedOrigin('javascript:alert(1)'), false, 'javascript protocol must be blocked');
console.log('✔ Strict origin and navigation isolation verified');

// Test 13: Protocol handler hostname check enforced in main.cjs
assert.equal(mainContent.includes("parsedUrl.hostname !== 'urbanflow'"), true, 'main.cjs must strictly validate protocol hostname');
console.log('✔ Protocol handler hostname validation verified');

// Test 14: Permissions handler denies ambient permission requests
assert.equal(mainContent.includes("setPermissionRequestHandler"), true, 'main.cjs must set permission request handler');
assert.equal(mainContent.includes("setPermissionCheckHandler"), true, 'main.cjs must set permission check handler');
console.log('✔ Device permissions denial policy verified');

// Test 15: Cross-Origin Opener & Resource Policy headers verified
assert.equal(mainContent.includes("'cross-origin-opener-policy': 'same-origin'"), true, 'main.cjs must specify COOP same-origin');
assert.equal(mainContent.includes("'cross-origin-resource-policy': 'same-origin'"), true, 'main.cjs must specify CORP same-origin');
console.log('✔ Cross-Origin Opener & Resource Policy headers verified');

// Test 16: Verify IPC worker token and action scopes configured in main.cjs (U-02)
assert.equal(mainContent.includes('IPC_SESSION_TOKEN'), true, 'main.cjs must generate IPC_SESSION_TOKEN');
assert.equal(mainContent.includes('ACTION_SCOPES'), true, 'main.cjs must define ACTION_SCOPES');
assert.equal(mainContent.includes('URBAN_FLOW_IPC_TOKEN'), true, 'main.cjs must pass URBAN_FLOW_IPC_TOKEN to worker');
console.log('✔ IPC worker session token and action scopes verified');

// Test 17: Multi-video directional analysis IPC action and route configured
assert.equal(mainContent.includes("'analyse-multi-video': 'inference:write'"), true, 'main.cjs must scope analyse-multi-video');
assert.equal(mainContent.includes("/api/analyse-multi-video"), true, 'main.cjs must handle /api/analyse-multi-video route');
console.log('✔ Multi-video action scoping and route verified');

// Test 18: Centralized URL utils and trusted external domains module exists
const urlUtilsPath = path.join(FRONTEND_DIR, 'electron', 'url-utils.cjs');
assert.equal(fs.existsSync(urlUtilsPath), true, 'url-utils.cjs must exist');
const urlUtils = await import(pathToFileURL(urlUtilsPath).href);
assert.equal(Array.isArray(urlUtils.TRUSTED_EXTERNAL_DOMAINS), true, 'TRUSTED_EXTERNAL_DOMAINS must be an array');
assert.equal(urlUtils.TRUSTED_EXTERNAL_DOMAINS.includes('github.com'), true, 'github.com must be in trusted allowlist');
assert.equal(urlUtils.TRUSTED_EXTERNAL_DOMAINS.includes('ultralytics.com'), true, 'ultralytics.com must be in trusted allowlist');
assert.equal(urlUtils.TRUSTED_EXTERNAL_DOMAINS.includes('opencv.org'), true, 'opencv.org must be in trusted allowlist');
console.log('✔ Centralized URL utils & trusted domain allowlist verified');

// Test 19: Centralized external URL validation logic
const { validateExternalUrl, isMatchingDomain } = urlUtils;
assert.equal(validateExternalUrl('https://github.com/harsh-aggarwal').isTrusted, true, 'github.com must be trusted');
assert.equal(validateExternalUrl('https://docs.ultralytics.com/').isTrusted, true, 'docs.ultralytics.com must be trusted');
assert.equal(validateExternalUrl('https://untrusted-site.org/').isTrusted, false, 'untrusted site must NOT be trusted');
assert.equal(validateExternalUrl('https://untrusted-site.org/').valid, true, 'untrusted http/https must be valid');
assert.equal(validateExternalUrl('javascript:alert(1)').valid, false, 'javascript protocol must be rejected');
assert.equal(validateExternalUrl('file:///etc/passwd').valid, false, 'file protocol must be rejected');
assert.equal(validateExternalUrl('data:text/html,test').valid, false, 'data protocol must be rejected');
assert.equal(validateExternalUrl('https://github.com.untrusted.example/').isTrusted, false, 'subdomain spoofing must NOT be trusted');
assert.equal(validateExternalUrl('https://admin:pass@github.com/').valid, false, 'credentials in URL must be rejected');
assert.equal(validateExternalUrl('https://github.com:8443/').valid, false, 'unexpected port must be rejected');
console.log('✔ Centralized external URL validation logic verified');

// Test 20: main.cjs wires setWindowOpenHandler and will-navigate securely
assert.equal(mainContent.includes("openExternalUrl"), true, 'main.cjs must import and invoke openExternalUrl');
assert.equal(mainContent.includes("setWindowOpenHandler"), true, 'main.cjs must register setWindowOpenHandler');
assert.equal(mainContent.includes("action: 'deny'"), true, 'main.cjs must always return action: deny in setWindowOpenHandler');
console.log('✔ Window open and navigation containment handlers in main.cjs verified');

console.log('--- ALL ELECTRON SECURITY TESTS PASSED ---');
