/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

import fs from 'fs';
import path from 'path';

const FRONTEND_DIR = 'C:\\Users\\HARSH AGGARWAL\\.gemini\\antigravity\\scratch\\Urban-Flow\\frontend';
const OUTPUT_PUBLIC = path.join(FRONTEND_DIR, '.output', 'public');
const DIST_CLIENT = path.join(FRONTEND_DIR, 'dist', 'client');
const SERVER_MJS = path.join(FRONTEND_DIR, '.output', 'server', 'index.mjs');

// 1. Copy public assets from .output/public to dist/client
fs.cpSync(OUTPUT_PUBLIC, DIST_CLIENT, { recursive: true });
console.log('Copied .output/public -> dist/client');

// 2. Render SSR HTML using server bundle
const serverUrl = 'file:///' + SERVER_MJS.replace(/\\/g, '/');
const { default: server } = await import(serverUrl);

const env = {
  ASSETS: {
    fetch: async () => new Response('Not Found', { status: 404 }),
  },
};

const req = new Request('http://localhost/');
const res = await server.fetch(req, env);
const html = await res.text();

const indexHtmlPath = path.join(DIST_CLIENT, 'index.html');
fs.writeFileSync(indexHtmlPath, html, 'utf-8');
console.log(`Successfully generated exact SSR index.html (${html.length} bytes)`);
