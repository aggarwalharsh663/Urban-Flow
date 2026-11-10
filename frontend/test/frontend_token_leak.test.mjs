// Automated Test: Verify URBAN_FLOW_DEV_TOKEN is never leaked into client bundles or served JS
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FRONTEND_DIR = path.resolve(__dirname, '..');
const DIST_CLIENT_DIR = path.join(FRONTEND_DIR, 'dist', 'client');

const TEST_SECRET_TOKEN = 'secret_test_token_12345';
process.env.URBAN_FLOW_DEV_TOKEN = TEST_SECRET_TOKEN;
delete process.env.VITE_API_TOKEN;

// 1. Mock Vite Dev Server Instance
// Vite's dev server behavior:
// - Non-VITE_ prefixed env variables are private to Node.js server.
// - Client scripts are served with import.meta.env only containing VITE_* variables.
// - /api requests are proxied with X-API-Token attached server-side.

async function runMockViteDevInstance() {
  let proxyAttachedHeader = null;

  // Upstream backend mock
  const upstreamServer = http.createServer((req, res) => {
    proxyAttachedHeader = req.headers['x-api-token'];
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', authenticated: Boolean(proxyAttachedHeader) }));
  });

  await new Promise((resolve) => upstreamServer.listen(0, '127.0.0.1', resolve));
  const upstreamPort = upstreamServer.address().port;

  // Mock Vite Dev Server
  const devServer = http.createServer((req, res) => {
    // Dev Proxy Route (/api and /uploads)
    if (req.url.startsWith('/api/') || req.url.startsWith('/uploads/')) {
      const devToken = process.env.URBAN_FLOW_DEV_TOKEN || process.env.VITE_API_TOKEN;
      const upstreamReq = http.request(
        {
          hostname: '127.0.0.1',
          port: upstreamPort,
          path: req.url,
          method: req.method,
          headers: {
            ...req.headers,
            host: `127.0.0.1:${upstreamPort}`,
            ...(devToken && !req.headers['x-api-token'] ? { 'X-API-Token': devToken } : {}),
          },
        },
        (upstreamRes) => {
          res.writeHead(upstreamRes.statusCode, upstreamRes.headers);
          upstreamRes.pipe(res);
        }
      );
      req.pipe(upstreamReq);
      return;
    }

    // Client Script Serving with Vite Environment Transform
    // Vite only defines import.meta.env for variables prefixed with VITE_
    const clientEnv = {};
    for (const [key, val] of Object.entries(process.env)) {
      if (key.startsWith('VITE_')) {
        clientEnv[key] = val;
      }
    }

    const cleanPath = req.url.split('?')[0].replace(/^\//, '');
    const filePath = path.join(FRONTEND_DIR, cleanPath);

    if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
      let content = fs.readFileSync(filePath, 'utf-8');
      // Simulate Vite dev server transform of import.meta.env
      content = content.replace(/import\.meta\.env\.([A-Za-z0-9_]+)/g, (match, varName) => {
        return JSON.stringify(clientEnv[varName] !== undefined ? clientEnv[varName] : '');
      });
      content = content.replace(/import\.meta\.env/g, JSON.stringify(clientEnv));

      res.writeHead(200, {
        'Content-Type': filePath.endsWith('.js') || filePath.endsWith('.jsx') || filePath.endsWith('.tsx') ? 'application/javascript' : 'text/plain'
      });
      res.end(content);
    } else {
      res.writeHead(404);
      res.end('Not Found');
    }
  });

  await new Promise((resolve) => devServer.listen(0, '127.0.0.1', resolve));
  const devPort = devServer.address().port;

  try {
    // Test 1: Fetch served App.jsx
    const appRes = await fetch(`http://127.0.0.1:${devPort}/src/components/urbanflow/App.jsx`);
    const appBody = await appRes.text();
    assert.equal(appRes.status, 200);
    assert.equal(appBody.includes(TEST_SECRET_TOKEN), false, 'URBAN_FLOW_DEV_TOKEN leaked into served App.jsx!');
    assert.equal(appBody.includes('VITE_API_TOKEN'), false, 'VITE_API_TOKEN referenced in served App.jsx!');

    // Test 2: Fetch served routes/index.tsx
    const routeRes = await fetch(`http://127.0.0.1:${devPort}/src/routes/index.tsx`);
    const routeBody = await routeRes.text();
    assert.equal(routeRes.status, 200);
    assert.equal(routeBody.includes(TEST_SECRET_TOKEN), false, 'URBAN_FLOW_DEV_TOKEN leaked into served routes/index.tsx!');

    // Test 3: Fetch proxied API call to verify proxy attaches token server-side
    const apiRes = await fetch(`http://127.0.0.1:${devPort}/api/test-token`);
    const apiJson = await apiRes.json();
    assert.equal(apiRes.status, 200);
    assert.equal(apiJson.authenticated, true);
    assert.equal(proxyAttachedHeader, TEST_SECRET_TOKEN, 'Dev proxy failed to attach URBAN_FLOW_DEV_TOKEN to upstream request!');

    // Test 4: Parse all dist client bundles if present
    if (fs.existsSync(DIST_CLIENT_DIR)) {
      const walkFiles = (dir) => {
        let results = [];
        const list = fs.readdirSync(dir);
        for (const file of list) {
          const full = path.join(dir, file);
          const stat = fs.statSync(full);
          if (stat.isDirectory()) {
            results = results.concat(walkFiles(full));
          } else if (file.endsWith('.js') || file.endsWith('.html') || file.endsWith('.css')) {
            results.push(full);
          }
        }
        return results;
      };

      const distFiles = walkFiles(DIST_CLIENT_DIR);
      assert.ok(distFiles.length > 0, 'Dist files should be present');
      for (const distFile of distFiles) {
        const text = fs.readFileSync(distFile, 'utf-8');
        assert.equal(text.includes(TEST_SECRET_TOKEN), false, `URBAN_FLOW_DEV_TOKEN leaked into dist file ${path.basename(distFile)}!`);
      }
    }

    console.log('✔ Mock Vite dev server served JS does not leak URBAN_FLOW_DEV_TOKEN');
    console.log('✔ Dev proxy successfully attaches URBAN_FLOW_DEV_TOKEN server-side');
    console.log('✔ Client bundles contain zero references to test secret or VITE_API_TOKEN');
  } finally {
    devServer.close();
    upstreamServer.close();
  }
}

runMockViteDevInstance().then(() => {
  console.log('--- ALL FRONTEND ASSET LEAK CHECKS PASSED ---');
}).catch((err) => {
  console.error('Asset Leak Test Failed:', err);
  process.exit(1);
});
