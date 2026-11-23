/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

export function renderErrorPage(): string {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>This page didn't load</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      :root {
        --paper: #121820;
        --card: #1a2230;
        --ink: #f3f4f6;
        --ink-soft: #9ca3af;
        --rule: #f3f4f6;
        --signal: #00e5ff;
        --signal-ink: #000;
        --stop: #ef4444;
      }
      body {
        font: 15px/1.5 "JetBrains Mono", ui-monospace, monospace;
        background: var(--paper);
        color: var(--ink);
        display: grid;
        place-items: center;
        min-height: 100vh;
        margin: 0;
        padding: 1.5rem;
        box-sizing: border-box;
      }
      .card {
        max-width: 32rem;
        width: 100%;
        text-align: center;
        padding: 2.2rem;
        background: var(--card);
        border: 3px solid var(--rule);
        box-shadow: 8px 8px 0 #000;
      }
      .badge {
        display: inline-block;
        padding: 4px 10px;
        background: var(--stop);
        color: #fff;
        font-weight: 700;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 1rem;
      }
      h1 {
        font-size: 1.5rem;
        font-weight: 800;
        text-transform: uppercase;
        margin: 0 0 0.75rem;
        letter-spacing: -0.02em;
      }
      p {
        color: var(--ink-soft);
        margin: 0 0 1.75rem;
        font-size: 13px;
        line-height: 1.6;
      }
      .actions {
        display: flex;
        gap: 0.75rem;
        justify-content: center;
        flex-wrap: wrap;
      }
      a, button {
        padding: 0.6rem 1.25rem;
        font: 700 13px "JetBrains Mono", monospace;
        text-transform: uppercase;
        cursor: pointer;
        text-decoration: none;
        border: 2px solid var(--rule);
        box-shadow: 3px 3px 0 var(--ink);
        transition: transform 0.1s;
      }
      a:hover, button:hover {
        transform: translate(-1px, -1px);
        box-shadow: 4px 4px 0 var(--ink);
      }
      .primary {
        background: var(--signal);
        color: var(--signal-ink);
      }
      .secondary {
        background: var(--card);
        color: var(--ink);
      }
      .footer-note {
        margin-top: 1.75rem;
        padding-top: 0.85rem;
        border-top: 1px dashed var(--rule);
        font-size: 10px;
        color: var(--ink-soft);
      }
    </style>
  </head>
  <body>
    <div class="card">
      <div class="badge">Traffic Engine Fail-Safe</div>
      <h1>This page didn't load</h1>
      <p>Something went wrong on our end. You can try refreshing or head back home.</p>
      <div class="actions">
        <button class="primary" onclick="location.reload()">Try again</button>
        <a class="secondary" href="/">Go home</a>
      </div>
      <div class="footer-note">
        UrbanFlow Adaptive Traffic Signal System · Copyright © 2026 Harsh Aggarwal
      </div>
    </div>
  </body>
</html>`;
}
