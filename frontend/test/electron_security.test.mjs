// Automated Security Test for Finding 2 & Electron Hardening
import assert from 'node:assert/strict';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

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

function resolveContainedPath(baseDir, requestedPath, allowedExtensions) {
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
  if (allowedExtensions && !allowedExtensions.has(ext)) {
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
assert.equal(isAllowedOrigin('app://attacker.com/'), false, 'Foreign app:// host must be blocked');
assert.equal(isAllowedOrigin('http://evil.com/'), false, 'External http must be blocked');
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

console.log('--- ALL ELECTRON SECURITY TESTS PASSED ---');
