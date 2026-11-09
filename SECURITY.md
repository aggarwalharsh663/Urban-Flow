# Security Architecture & Controls — Urban Flow

## 1. Security Overview

Urban Flow implements a defense-in-depth security architecture covering scoped API authorization, origin isolation, path containment, verified on-device privacy controls, and disk quota enforcement.

| Domain | Control Area | Implementation |
|---|---|---|
| Authentication & Authorization (R1, R2) | Per-install token & scoped permission model | Constant-time token verification, scoped roles (`read`, `reports:write`, `inference:write`, `admin`), short-lived HMAC media tickets |
| Host & Origin Isolation (R5 Part B) | Strict Host header & explicit CORS origin validation | Approved Host allowlist (`127.0.0.1`, `localhost`), explicit CORS origins, state-changing CSRF origin checks |
| Electron Protocol Security | Strict filesystem containment on `app://` | Path normalization, traversal rejection, extension allowlists, portless custom scheme |
| Desktop Hardening (R2) | ContextBridge IPC, action allowlists & DPAPI encryption | Windows DPAPI token encryption at rest, isolated preload, no raw token retrieval IPC |
| Storage Quota & Upload Safety (R4, R6) | Enforced 500 MB storage cap & streaming uploads | Thread-safe `StorageManager` reservation, automated LRU eviction, chunked streaming uploads |
| Privacy Controls (R5 Part A) | On-device face & license plate redaction | Local YOLO privacy blur across persons and vehicle registration plates before optional Gemini transmission (fail-closed) |
| Model Integrity | SHA-256 model weight verification | Block unpinned PyTorch weights to prevent deserialization vulnerabilities |
| Worker Lifecycle (R6) | Process isolation & timeout cancellation | Cooperative request cancellation on IPC timeout, bounded memory processing |
| Launchers & Environments (R7) | Strict separation of production & development | Production execution never enables `--reload`; development launcher isolated |

---

## 2. API Authentication & Scoped Authorization (R1 & R2)

- **Cryptographic Generation**: A 256-bit URL-safe token (`secrets.token_urlsafe(32)`) is generated on initialization.
- **At-Rest Protection**: Persisted in `.urban_flow_token` using Windows Data Protection API (DPAPI) encryption (`CryptProtectData`) and restricted user filesystem permissions (`0o600`), or configured via `URBAN_FLOW_API_TOKEN`.
- **Scoped Authorization Model (R1)**:
  - `read`: Read reports, retrieve directions, and access non-sensitive endpoints.
  - `reports:write`: Calculate plans, run simulations, update cycle timings and vehicle counts.
  - `inference:write`: Submit images and videos for local or opt-in cloud vision analysis.
  - `admin`: Storage management, system diagnostics, and configuration.
  - Master token holds `ALL_SCOPES`. Derived tokens are cryptographically generated using HMAC-SHA256 (`generate_scoped_token`).
- **No Query-String Secrets (R2)**: Ordinary API endpoints reject tokens in URL query strings. Authentication is strictly accepted via `X-API-Token` header or `Authorization: Bearer <token>`.
- **Media Preview Tickets**: Web `<img>` previews use short-lived HMAC tickets (`generate_media_ticket`) valid for 5 minutes, eliminating master token exposure in URLs, browser history, or server access logs.
- **Timing Defense**: All token and ticket verifications use constant-time comparison (`secrets.compare_digest`).

---

## 3. Host Header & Origin Isolation (R5 Part B)

- **Host Header Validation**: FastAPI middleware validates the `Host` header against an explicit allowlist:
  - `127.0.0.1:8000`, `localhost:8000` (Backend API)
  - `127.0.0.1:5174`, `localhost:5174` (Dev Frontend)
  - `127.0.0.1`, `localhost`, `testserver`
  - Unexpected or spoofed Host headers are rejected with `HTTP 400 Bad Request`.
- **No Wildcard CORS**: Wildcard `*` origins are strictly prohibited.
- **CSRF / Origin Check**: State-changing requests (`POST`, `PUT`, `DELETE`) with an `Origin` header are verified against approved origins; unapproved origins receive `HTTP 403 Forbidden`.

---

## 4. Electron Desktop Architecture & Preload Security (R2 & R6)

- **Portless Custom Protocol**: In desktop mode, the renderer communicates over `app://urbanflow/` without binding external network ports.
- **IPC Action Allowlist**: The main process validates IPC actions against an explicit set (`health`, `simulate`, `calculate-signal-plan`, `analyse-image`, `analyse-video`, `get-report`, `update-cycle`, `update-counts`, `cancel`).
- **No Raw Token in Renderer**: The renderer cannot retrieve the master API token via IPC (`get-api-token` is removed).
- **Navigation & Redirect Locking**: `will-navigate` and `will-redirect` listeners lock renderer navigation strictly to `app://urbanflow/`. External links open in default OS browser.
- **Ambient Permissions Blocked**: `setPermissionRequestHandler` and `setPermissionCheckHandler` deny all ambient hardware/device permission requests (camera, microphone, geolocation).

---

## 5. Storage Quota & File Upload Safety (R4 & R6)

- **500 MB Hard Storage Budget (R4)**: `GLOBAL_STORAGE_MANAGER` enforces an absolute 500 MB storage cap across uploads, generated reports, and database files.
- **Pre-Write Capacity Reservation**: Inbound uploads and reports reserve capacity before writing to disk. Requests exceeding available capacity trigger automated cleanup. If storage remains over quota, requests fail with `HTTP 507 Insufficient Storage`.
- **Automated Eviction**:
  1. Expired uploads (> 24h) and expired reports (> 72h) are deleted first.
  2. If storage still exceeds 500 MB, oldest eligible non-expired uploads are evicted.
  3. Active processing files are protected in `_active_files` and never deleted during cleanup.
- **Streaming Upload Processing (R6)**: File uploads are streamed in 64 KB chunks directly to disk. In-memory whole-file buffering (`arrayBuffer()`) is eliminated.
- **Decompression Bomb Protection**: Pillow `MAX_IMAGE_PIXELS` set to 16,777,216 pixels. Max image dimensions 4096 x 4096 px. Max video duration 60s, max 1800 frames.

---

## 6. Privacy & Cloud Processing Consent (R5 Part A)

- **Local-Only Default**: Urban Flow operates in 100% offline/local mode by default using local YOLOv8 weights.
- **Explicit Cloud Consent**: Media frames are NEVER transmitted to Google Gemini unless:
  1. `GEMINI_API_KEY` is configured in `.env`, AND
  2. The user explicitly opts in by enabling the cloud vision toggle (`use_cloud_ai=True`).
- **Verified On-Device Privacy Redaction (R5 Part A)**:
  - Before any frame is resized or encoded for cloud transmission, `services.privacy.redact_frame_for_cloud` executes on-device.
  - Pedestrians and persons (`cls == 0`) are redacted with heavy Gaussian blur across their entire bounding box to obscure faces and identifying characteristics.
  - Vehicles (`cls in {2, 3, 5, 7}`) have their lower license plate bumper region and upper driver compartment blurred.
  - **Fail-Closed Guarantee**: If on-device privacy redaction cannot be completed or the local model is unavailable, cloud transmission is blocked (`GeminiAnalysisError`). No unredacted frame ever leaves the device.

---

## 7. Rate Limiting & Concurrency Control

- **Sliding-Window Rate Limiter**: Multi-worker SQLite database in WAL mode with strict per-client limits:
  - Inference (`/api/analyse-*`): 10 req/min
  - Simulation (`/api/simulate`, `/api/calculate-signal-plan`): 30 req/min
  - Reports (`/api/reports/*`): 60 req/min
  - General (`/api/directions`, etc.): 120 req/min
  - Exceeding returns `HTTP 429 Too Many Requests` with `Retry-After`.
- **Concurrency Bounding**: Inference semaphore limits concurrent analyses to 2, preventing CPU starvation.
- **Request Cancellation (R6)**: Timed-out IPC requests send a cooperative `cancel` signal to the Python worker, which aborts processing and cleans up temporary files without state corruption.

---

## 8. Atomic Report Persistence

- Report updates use atomic file replacement (`tempfile.mkstemp` + `os.replace`) and concurrency locks, preventing race conditions or corrupted JSON files.
- Modification history records version numbers, timestamps, previous state, and modifying channel (`api` vs `ipc`).
- Report directories inherit strict restrictive filesystem permissions (`secure_file_permissions`).

---

## 9. Security Headers & Transport Security

FastAPI and Electron inject:
- `Content-Security-Policy`: Restricts scripts to trusted origins and allows inline styles for UI components.
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Cross-Origin-Opener-Policy: same-origin`
- `Cross-Origin-Resource-Policy: same-origin`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`

---

## 10. Production Launchers & Environment Isolation (R7)

- **Production Launcher (`run-backend.ps1`, `start.bat`)**:
  - Always executes in non-reload mode (`--no-server-header`, `--host 127.0.0.1`).
  - Command-line debug parameters and `--reload` flags are completely removed from production launchers.
- **Development Launcher (`run-backend-dev.ps1`)**:
  - Isolated dedicated script for local contributors. Requires explicit `URBAN_FLOW_ENV=development` confirmation.
