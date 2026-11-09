# Security Architecture & Controls — Urban Flow

## 1. Security Overview

Urban Flow implements a defense-in-depth security architecture covering API authentication, origin isolation, path containment, and local privacy controls.

| Domain | Control Area | Implementation |
|---|---|---|
| Authentication & CORS | Per-launch token validation & explicit origin policy | Constant-time token verification, no wildcard CORS |
| Electron Protocol Security | Strict filesystem containment on `app://` | Path normalization, traversal rejection, extension whitelist |
| Data Integrity | Atomic report persistence & audit logging | Atomic writes, versioning, revision history |
| Upload Security | Magic byte validation & sandboxing | Header signature verification, 100MB cap, CSP sandbox headers |
| Resource Protection | Multi-worker rate limiting & concurrency semaphores | SQLite WAL-mode sliding window, inference bounds |
| Privacy Controls | Local inference default & data redaction | On-device YOLO privacy blur before cloud API |
| Model Integrity | SHA-256 model weight verification | Block unpinned PyTorch weights to prevent deserialization |
| Information Security | Error sanitization & path disclosure prevention | Masked internal exceptions, generic client errors |
| Desktop Hardening | ContextBridge IPC & DPAPI encryption at rest | Windows DPAPI token encryption, isolated preload |

---

## 2. API Authentication & Token Management

- **Cryptographic Generation**: A 256-bit URL-safe token (`secrets.token_urlsafe(32)`) is generated on initialization.
- **Storage**: Stored in `.urban_flow_token` with DPAPI encryption at rest on Windows and restricted user file permissions (`0o600`), or provided via `URBAN_FLOW_API_TOKEN` environment variable.
- **Enforcement**: Sensitive endpoints (`/api/calculate-signal-plan`, `/api/simulate`, `/api/analyse-image`, `/api/analyse-video`, `/api/reports/*`) require authentication via `X-API-Token` header, `Authorization: Bearer <token>`, or `api_token` query parameter.
- **Timing Defense**: Validated using constant-time string comparison (`secrets.compare_digest`).

---

## 3. CORS & Origin Isolation

- **No Wildcard CORS**: `allow_origins=["*"]` has been eliminated.
- **Approved Origins Only**: Explicit origins permitted:
  - `http://127.0.0.1:5174`, `http://localhost:5174` (Dev Frontend)
  - `http://127.0.0.1:8000`, `http://localhost:8000` (Backend API)
  - `app://urbanflow` (Desktop Electron runtime)
- **CSRF / Origin Check**: State-changing methods (`POST`, `PUT`, `DELETE`) with an `Origin` header are checked against approved origins; unexpected origins receive `HTTP 403 Forbidden`.

---

## 4. Electron `app://` Protocol Hardening

- **Containment Checks**: Path resolution utilizes `resolveContainedPath` which decodes recursive URI encoding, strips traversal sequences, and confirms path containment within `CLIENT_DIR` or `UPLOAD_DIR`.
- **Sensitive File Blocklist**: Requests for `.env`, `.git`, `.py`, `.pt`, `.lock`, `.bat`, or any hidden dotfiles are unconditionally rejected.
- **Extension Allowlists**:
  - Frontend assets: `.html`, `.js`, `.mjs`, `.css`, `.json`, `.png`, `.jpg`, `.jpeg`, `.svg`, `.ico`, `.woff`, `.woff2`, `.txt`
  - Uploaded media: `.jpg`, `.jpeg`, `.png`, `.mp4`
- **Execution Isolation**: Uploaded files are served with `Content-Security-Policy: default-src 'none'; sandbox` and `X-Content-Type-Options: nosniff`. HTML/JS files uploaded by an attacker cannot execute in the application context.

---

## 5. File Upload & Processing Safety

- **Magic Byte Validation**: File headers are inspected for exact byte signatures (`\xFF\xD8\xFF` for JPEG, `\x89PNG\r\n\x1a\n` for PNG, `ftyp` for MP4).
- **Size Limits**: Enforced 100 MB maximum size across both FastAPI streaming and Electron IPC.
- **Decompression Bomb Protection**: Pillow `Image.MAX_IMAGE_PIXELS` set to 16,777,216 pixels. Max image dimensions 4096 x 4096 px. Max video duration 60s, max 1800 frames.
- **Model Integrity**: YOLOv8 weights are verified against pinned SHA-256 hashes (`yolov8n.pt`, `yolov8s.pt`, `yolov8m.pt`).
- **Automatic Cleanup**: Upload and report retention cleaner purges temporary and expired files according to retention limits (24h uploads, 72h reports, 500 MB max storage).

---

## 6. Privacy & Cloud Processing Consent

- **Local-Only Default**: Urban Flow operates in 100% local mode by default using local YOLOv8 weights.
- **Explicit Consent**: Media frames are NEVER transmitted to Google Gemini unless:
  1. `GEMINI_API_KEY` is configured, AND
  2. The user explicitly enables the cloud processing toggle (`use_cloud_ai=True`).
- **Transparency**: The UI displays active processing modes and visible notices before transmitting data.

---

## 7. Rate Limiting & Concurrency

- **Sliding-Window Rate Limiter**: Multi-process SQLite WAL-mode rate limiter with configurable limits:
  - Inference (`/api/analyse-*`): 10 req/min
  - Simulation (`/api/simulate`, `/api/calculate-signal-plan`): 30 req/min
  - Reports (`/api/reports/*`): 60 req/min
  - Exceeding returns `HTTP 429 Too Many Requests` with `Retry-After`.
- **Concurrency Bounding**: Inference semaphore limits concurrent analyses to 2, preventing CPU starvation.

---

## 8. Atomic Report Persistence

- Report updates use atomic file replacement (`tempfile` + `os.replace`) and concurrency locks, preventing race conditions or corrupted JSON files.
- Modification history records version numbers, timestamps, and previous state.

---

## 9. Security Headers

FastAPI and Electron inject:
- `Content-Security-Policy`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`

---

## 10. Supply Chain & Launchers

- Python dependencies are strictly pinned in `requirements.txt` and locked in `requirements.lock`.
- `setup.ps1` downloads exclusively from official PyPI (`https://pypi.org/simple`).
- Production launchers execute without development `--reload` mode.
