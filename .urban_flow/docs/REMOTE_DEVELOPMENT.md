# Urban Flow — Remote Development & Cloud Architecture Guide
<!--
  Urban Flow - Adaptive Traffic Signal System
  Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.

  Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
  Any additions, modifications, or contributed files to this project automatically
  and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
-->

This document outlines how **Harsh Aggarwal** can develop, test, debug, and build **Urban Flow** remotely from any device (phone, tablet, iPad, Chromebook, or another PC) **even when the primary laptop is completely powered off**.

---

## 1. Architectural Overview

When your local laptop is turned off, local processes and hardware ports cannot run. To work remotely with zero dependency on your physical machine, Urban Flow leverages three cloud layers:

```
                  ┌────────────────────────────────────────┐
                  │          Any Remote Device             │
                  │   (Browser, iPad, Phone, Other PC)     │
                  └──────────────────┬─────────────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
┌──────────────────┐       ┌──────────────────┐        ┌──────────────────┐
│ GitHub Codespaces│       │  Always-On Cloud │        │  GitHub Actions  │
│  (Cloud Dev IDE) │       │   Server / VPS   │        │   Cloud CI/CD    │
├──────────────────┤       ├──────────────────┤        ├──────────────────┤
│ • Full VS Code   │       │ • 24/7 background│        │ • 350 Tests Auto │
│ • Python & Node  │       │   video analysis │        │ • C# Windows EXE │
│ • Ports 8000/3000│       │ • VS Code Tunnel │        │   compilation    │
│ • Zero install   │       │ • Oracle / AWS   │        │ • Zip packaging  │
└──────────────────┘       └──────────────────┘        └──────────────────┘
```

---

## 2. Method 1 (Recommended): GitHub Codespaces — 1-Click Instant Cloud IDE

**Best for:** Daily coding, fixing bugs, running test suites, and viewing frontend/backend output without touching local hardware.

### Features Pre-Configured:
- Pre-configured `.devcontainer/devcontainer.json` and `.devcontainer/post-create.sh`.
- Automated installation of Python 3.11, Node.js 20, OpenCV system binaries (`libgl1`, `ffmpeg`), and PyTorch/Ultralytics dependencies.
- Automatic port forwarding for **Port 8000** (Backend FastAPI API) and **Port 3000** (Frontend Vite web app).
- Free 60 core-hours per month included with personal GitHub accounts.

### How to Launch (from any browser, phone, or tablet):
1. Navigate to: `https://github.com/aggarwalharsh663/Urban-Flow`
2. Click the green **Code** button -> select the **Codespaces** tab.
3. Click **Create codespace on main**.
4. In under 60 seconds, a full VS Code IDE runs directly in your web browser.
5. In the terminal, run tests:
   ```bash
   pytest backend/tests
   cd frontend && npm run test -- --run
   ```
6. To run the backend and frontend simultaneously:
   - Terminal 1: `python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`
   - Terminal 2: `cd frontend && npm run dev`
   - Codespaces will pop up a notification: *"Your application running on port 3000 is available at https://..."* — click to interact with the live UI in your browser!

---

## 3. Method 2: Always-On Dedicated Cloud VPS (24/7 Autonomous Workers)

**Best for:** If you want a server running continuous YOLO traffic analysis or public API endpoints 24/7 even while you sleep.

### Recommended Providers:
- **Oracle Cloud Infrastructure (OCI) Always Free:** 4 ARM Ampere OCPUs, 24 GB RAM, 200 GB SSD (100% Free Forever).
- **DigitalOcean / Hetzner / Linode / AWS EC2:** $4 to $10/month Linux instances.

### Setup Steps:
1. SSH into your cloud VM:
   ```bash
   ssh ubuntu@<YOUR_SERVER_IP>
   ```
2. Clone the repository:
   ```bash
   git clone https://github.com/aggarwalharsh663/Urban-Flow.git
   cd Urban-Flow
   ```
3. Set up VS Code Remote Tunnel (allows you to code from `vscode.dev`):
   ```bash
   # Download VS Code CLI
   curl -Lk 'https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64' --output vscode_cli.tar.gz
   tar -xf vscode_cli.tar.gz
   ./code tunnel --name urbanflow-cloud
   ```
   - Log in once with your GitHub account.
   - Now, you can open `https://vscode.dev/tunnel/urbanflow-cloud` from any device anywhere in the world and have an always-on persistent workstation.

4. Run Backend as a Background Service (`systemd`):
   Create `/etc/systemd/system/urbanflow.service`:
   ```ini
   [Unit]
   Description=Urban Flow Adaptive Signal Engine
   After=network.target

   [Service]
   User=ubuntu
   WorkingDirectory=/home/ubuntu/Urban-Flow
   ExecStart=/usr/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
   Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now urbanflow
   ```

---

## 4. Method 3: Cloud Windows Build Engine (GitHub Actions)

**Best for:** Building `Urban Flow Setup.exe` and `Urban-Flow-v1.0-Standalone.zip` without needing a Windows machine running.

When you modify code from GitHub Codespaces or your phone:
1. Commit and push your changes to `main`.
2. Go to the **Actions** tab on GitHub: `https://github.com/aggarwalharsh663/Urban-Flow/actions`.
3. Select **Build Windows Deliverables** -> click **Run workflow**.
4. GitHub spins up a clean Microsoft Windows Server runner (`windows-latest`), compiles `launcher.cs`, `setup_form.cs`, and `updater.cs` using native `csc.exe`, packages the standalone zip, and creates the setup executable.
5. Once completed (~3-4 minutes), download the fresh `Urban-Flow-Windows-Deliverables` artifact directly from GitHub onto any computer!

---

## 5. Operating Standards & Security Policies

- **Copyright Integrity:** Every created or edited file must carry Harsh Aggarwal's copyright header.
- **Verification Rule:** Before merging or deploying changes, ensure the test suite is 100% green:
  ```bash
  pytest backend/tests
  npm run test --prefix frontend -- --run
  node frontend/test/electron_security.test.mjs
  ```
