"""
Centralized Security Configuration and Enforcement for Urban Flow.
Defines security constants, authentication, rate limiting, file validation,
storage cleanup, model integrity, and atomic persistence.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from PIL import Image

# Setup security logger
logger = logging.getLogger("urban_flow.security")

# Base directory references
BASE_DIR = Path(__file__).resolve().parent


def get_writable_data_dir() -> Path:
    """
    Return a writable data directory for runtime artifacts (tokens, uploads, reports, rate limits).
    Supports execution from C:\\Program Files (trusted by AppLocker / Software Restriction Policies).
    Prioritizes:
      1. Explicit URBAN_FLOW_DATA_DIR environment variable
      2. Local BASE_DIR (if writable, e.g. portable / dev / test mode)
      3. Fallback to %LOCALAPPDATA%\\Urban Flow (if BASE_DIR is read-only, e.g. Program Files under AppLocker)
    """
    custom = os.getenv("URBAN_FLOW_DATA_DIR", "").strip()
    if custom:
        p = Path(custom).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    try:
        test_file = BASE_DIR / ".write_test"
        test_file.touch(exist_ok=True)
        test_file.unlink(missing_ok=True)
        return BASE_DIR
    except (PermissionError, OSError):
        appdata = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
        fallback = Path(appdata) / "Urban Flow" / "data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


DATA_DIR = get_writable_data_dir()
TOKEN_FILE = DATA_DIR / ".urban_flow_token"

# --- Security Constants ---
MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB maximum upload size
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4"}
ALLOWED_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS

# Image & Video Processing Limits (Anti-Decompression-Bomb & Resource Bounding)
MAX_IMAGE_WIDTH = 4096
MAX_IMAGE_HEIGHT = 4096
MAX_IMAGE_PIXELS = 16_777_216  # 16 Megapixels
MAX_VIDEO_DURATION_SECONDS = 60.0
MAX_VIDEO_FRAMES = 1800
MAX_VIDEO_WIDTH = 1920
MAX_VIDEO_HEIGHT = 1080

# Input Limits
MAX_JUNCTION_NAME_LENGTH = 100
MAX_VEHICLE_COUNT = 10_000
MAX_GEMINI_DETECTIONS = 500

# Concurrency & Timeouts
MAX_CONCURRENT_INFERENCES = 2
INFERENCE_TIMEOUT_SECONDS_IMAGE = 45
INFERENCE_TIMEOUT_SECONDS_VIDEO = 90

# Storage Retention & Cleanup
UPLOAD_RETENTION_HOURS = 24
REPORT_RETENTION_HOURS = 72
MAX_STORAGE_BYTES = 500 * 1024 * 1024  # 500 MB max total uploads & reports
MAX_REPORTS_COUNT = 500

# Verified SHA-256 Hashes for Supported YOLO Models
KNOWN_MODEL_HASHES = {
    "yolov8n.pt": "f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36",
    "yolov8s.pt": "1f47a78bf100391c2a140b7ac73a1caae18c32779be7d310658112f7ac9aa78a",
    "yolov8m.pt": "5d4a90cdc7a21786cc59cd19778e9eafff836df9e2da32524737c7ee6efe4fe5",
}

# Protect Pillow against decompression bombs
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


# --- 1. API Authentication & Token Management with At-Rest Protection ---
_api_token_cache: Optional[str] = None
_token_lock = threading.Lock()


def _dpapi_protect(plaintext: bytes) -> bytes:
    """Encrypt bytes using Windows DPAPI (CryptProtectData)."""
    if sys.platform != "win32":
        return plaintext
    try:
        import ctypes
        import ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        in_blob = DATA_BLOB(
            len(plaintext),
            ctypes.cast(ctypes.create_string_buffer(plaintext), ctypes.POINTER(ctypes.c_char)),
        )
        out_blob = DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "UrbanFlowToken",
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        ):
            raise RuntimeError("CryptProtectData failed")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception as e:
        logger.warning("DPAPI protect failed: %s", e)
        return plaintext


def _dpapi_unprotect(ciphertext: bytes) -> bytes:
    """Decrypt bytes using Windows DPAPI (CryptUnprotectData)."""
    if sys.platform != "win32":
        return ciphertext
    try:
        import ctypes
        import ctypes.wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        in_blob = DATA_BLOB(
            len(ciphertext),
            ctypes.cast(ctypes.create_string_buffer(ciphertext), ctypes.POINTER(ctypes.c_char)),
        )
        out_blob = DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        ):
            raise RuntimeError("CryptUnprotectData failed")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception as e:
        logger.warning("DPAPI unprotect failed: %s", e)
        return ciphertext


def secure_file_permissions(path: Path):
    """
    Apply strict file system ACLs/permissions to secure secrets at rest.
    On Windows, strips inherited permissions and grants exclusive access to current user.
    On POSIX, sets mode 0o600 for files or 0o700 for directories.
    """
    if not path.exists():
        return
    if sys.platform == "win32":
        try:
            username = os.environ.get("USERNAME")
            if username:
                perm = f"{username}:(OI)(CI)(F)" if path.is_dir() else f"{username}:(R,W)"
                subprocess.run(
                    ["icacls", str(path), "/inheritance:r", "/grant:r", perm],
                    capture_output=True,
                    check=False,
                )
        except Exception:
            pass
    elif hasattr(os, "chmod"):
        try:
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
        except Exception:
            pass


def get_or_create_api_token() -> str:
    """
    Retrieve or generate a cryptographically secure random API token.
    Token is encrypted at rest using Windows DPAPI (or restricted file permissions on POSIX).
    Precedence:
      1. Environment variable URBAN_FLOW_API_TOKEN
      2. Stored DPAPI-encrypted token in TOKEN_FILE (.urban_flow_token)
      3. Newly generated 256-bit token persisted with DPAPI encryption and restricted permissions
    """
    global _api_token_cache
    if _api_token_cache:
        return _api_token_cache

    with _token_lock:
        if _api_token_cache:
            return _api_token_cache

        # Check environment
        env_token = os.getenv("URBAN_FLOW_API_TOKEN", "").strip()
        if env_token:
            _api_token_cache = env_token
            return _api_token_cache

        # Check token file
        if TOKEN_FILE.is_file():
            try:
                saved = TOKEN_FILE.read_text(encoding="utf-8").strip()
                if saved.startswith("DPAPI:"):
                    raw_b64 = saved[6:]
                    decrypted = _dpapi_unprotect(base64.b64decode(raw_b64)).decode("utf-8").strip()
                    if decrypted and len(decrypted) >= 32:
                        _api_token_cache = decrypted
                        secure_file_permissions(TOKEN_FILE)
                        return _api_token_cache
                elif saved and len(saved) >= 32:
                    # Legacy plaintext token - migrate to DPAPI encryption
                    _api_token_cache = saved
                    if sys.platform == "win32":
                        try:
                            enc = _dpapi_protect(saved.encode("utf-8"))
                            TOKEN_FILE.write_text("DPAPI:" + base64.b64encode(enc).decode("ascii"), encoding="utf-8")
                        except Exception:
                            pass
                    secure_file_permissions(TOKEN_FILE)
                    return _api_token_cache
            except Exception as e:
                logger.warning("Could not read token file: %s", e)

        # Generate new cryptographically secure token
        new_token = secrets.token_urlsafe(32)
        try:
            if sys.platform == "win32":
                enc = _dpapi_protect(new_token.encode("utf-8"))
                payload = "DPAPI:" + base64.b64encode(enc).decode("ascii")
            else:
                payload = new_token
            TOKEN_FILE.write_text(payload, encoding="utf-8")
            secure_file_permissions(TOKEN_FILE)
            # Also secure .env if present
            env_file = BASE_DIR / ".env"
            if env_file.is_file():
                secure_file_permissions(env_file)
        except Exception as e:
            logger.warning("Could not persist generated API token: %s", e)

        _api_token_cache = new_token
        return _api_token_cache


def verify_api_token(candidate: Optional[str]) -> bool:
    """Constant-time token verification to prevent timing attacks."""
    if not candidate:
        return False
    candidate = candidate.strip()
    expected = get_or_create_api_token().strip()
    if secrets.compare_digest(candidate, expected):
        return True
    # Also valid if it matches any active scoped token
    return bool(get_token_scopes(candidate))


# --- Scoped Authorization Model (R1) ---
SCOPE_READ = "read"
SCOPE_REPORTS_WRITE = "reports:write"
SCOPE_INFERENCE_WRITE = "inference:write"
SCOPE_ADMIN = "admin"
ALL_SCOPES = {SCOPE_READ, SCOPE_REPORTS_WRITE, SCOPE_INFERENCE_WRITE, SCOPE_ADMIN}


def generate_scoped_token(scope: str) -> str:
    """
    Derive a cryptographically tied token strictly limited to the specified scope.
    Uses HMAC-SHA256 with the master per-install secret as key.
    """
    import hmac
    if scope not in ALL_SCOPES:
        raise ValueError(f"Invalid authorization scope: {scope}")
    master = get_or_create_api_token().encode("utf-8")
    sig = hmac.new(master, f"scope:{scope}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"uf_{scope[:4]}_{sig[:32]}"


def get_token_scopes(candidate: Optional[str]) -> set[str]:
    """
    Return the set of authorization scopes granted to the candidate token.
    Master token inherently holds ALL_SCOPES.
    """
    if not candidate:
        return set()
    candidate = candidate.strip()
    master = get_or_create_api_token().strip()
    if secrets.compare_digest(candidate, master):
        return set(ALL_SCOPES)

    for scope in ALL_SCOPES:
        scoped = generate_scoped_token(scope)
        if secrets.compare_digest(candidate, scoped):
            if scope in {SCOPE_REPORTS_WRITE, SCOPE_INFERENCE_WRITE, SCOPE_ADMIN}:
                return {scope, SCOPE_READ}
            return {scope}

    return set()


def verify_token_scope(candidate: Optional[str], required_scope: str) -> bool:
    """Verify token validity and required scope in constant time."""
    if not candidate or not required_scope:
        return False
    scopes = get_token_scopes(candidate)
    return required_scope in scopes


# --- Media Preview Tickets (R2, R3) ---
def generate_media_ticket(filename: str, expires_in_seconds: int = 300) -> str:
    """
    Generate a short-lived HMAC media ticket for a specific file,
    eliminating raw master API token disclosure in URLs or browser history.
    """
    import hmac
    master = get_or_create_api_token().encode("utf-8")
    expiry = int(time.time()) + expires_in_seconds
    payload = f"{filename}:{expiry}"
    sig = hmac.new(master, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{expiry}_{sig}"


def verify_media_ticket(filename: str, ticket: Optional[str]) -> bool:
    """Verify short-lived media ticket in constant time."""
    if not ticket or "_" not in ticket:
        return False
    import hmac
    try:
        expiry_str, sig = ticket.split("_", 1)
        expiry = int(expiry_str)
        if time.time() > expiry:
            return False
        master = get_or_create_api_token().encode("utf-8")
        payload = f"{filename}:{expiry}"
        expected_sig = hmac.new(master, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
        return secrets.compare_digest(sig, expected_sig)
    except Exception:
        return False


# --- 2. CORS & Origin Validation ---
DEFAULT_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5174",
    "http://localhost:5174",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "app://urbanflow",
]


def get_allowed_origins() -> list[str]:
    """
    Return allowed origins.
    Wildcard ('*') is strictly disallowed.
    """
    configured = os.getenv("ALLOWED_ORIGINS", "").strip()
    if not configured:
        return list(DEFAULT_ALLOWED_ORIGINS)

    origins = []
    for item in configured.split(","):
        origin = item.strip()
        if not origin:
            continue
        if origin == "*":
            logger.error("Wildcard '*' in ALLOWED_ORIGINS is prohibited. Ignoring wildcard.")
            continue
        origins.append(origin)

    return origins if origins else list(DEFAULT_ALLOWED_ORIGINS)


# --- Host Header Validation (R5 Part B) ---
DEFAULT_ALLOWED_HOSTS = [
    "127.0.0.1:8000",
    "localhost:8000",
    "127.0.0.1:5174",
    "localhost:5174",
    "127.0.0.1",
    "localhost",
    "testserver",
]


def get_allowed_hosts() -> set[str]:
    """Return explicit allowed Host headers for local server protection."""
    configured = os.getenv("ALLOWED_HOSTS", "").strip()
    if not configured:
        return set(DEFAULT_ALLOWED_HOSTS)
    hosts = set()
    for h in configured.split(","):
        clean = h.strip().lower()
        if clean:
            hosts.add(clean)
    return hosts or set(DEFAULT_ALLOWED_HOSTS)


# --- 3. Magic Bytes File Validation ---
MAGIC_BYTES = {
    ".jpg": [b"\xFF\xD8\xFF"],
    ".jpeg": [b"\xFF\xD8\xFF"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
}


def verify_magic_bytes(header: bytes, ext: str) -> bool:
    """Verify that file header bytes match the expected magic signature for the extension."""
    ext = ext.lower()
    if ext in MAGIC_BYTES:
        return any(header.startswith(sig) for sig in MAGIC_BYTES[ext])
    if ext == ".mp4":
        # MP4 ISO Base Media / QuickTime files have 'ftyp' at offset 4
        return len(header) >= 8 and header[4:8] == b"ftyp"
    return False


def validate_image_file(path: Path) -> tuple[int, int]:
    """
    Validate that the image is legitimate, decodable, and within bounded dimensions.
    Returns (width, height) on success; raises ValueError on failure.
    """
    if not path.is_file():
        raise ValueError("Image file does not exist.")

    # Read header and verify magic bytes
    with path.open("rb") as f:
        header = f.read(32)
    ext = path.suffix.lower()
    if not verify_magic_bytes(header, ext):
        raise ValueError(f"File magic signature does not match extension '{ext}'. Fake or malformed file.")

    try:
        with Image.open(path) as img:
            img.verify()  # Verify integrity
        # Re-open to read dimensions after verify()
        with Image.open(path) as img:
            width, height = img.size
            if width <= 0 or height <= 0:
                raise ValueError("Image dimensions must be positive.")
            if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
                raise ValueError(
                    f"Image dimensions ({width}x{height}) exceed maximum allowed ({MAX_IMAGE_WIDTH}x{MAX_IMAGE_HEIGHT})."
                )
            if (width * height) > MAX_IMAGE_PIXELS:
                raise ValueError(
                    f"Image total pixels ({width * height}) exceed maximum allowed ({MAX_IMAGE_PIXELS})."
                )
            return width, height
    except Exception as e:
        raise ValueError(f"Image validation failed: {e}") from e


def validate_video_file(path: Path) -> tuple[int, int, float, int]:
    """
    Validate that the video is decodable, has reasonable frame count, fps, and duration.
    Returns (width, height, fps, frame_count) on success; raises ValueError on failure.
    """
    import cv2

    if not path.is_file():
        raise ValueError("Video file does not exist.")

    with path.open("rb") as f:
        header = f.read(32)
    ext = path.suffix.lower()
    if not verify_magic_bytes(header, ext):
        raise ValueError(f"File magic signature does not match MP4 video container. Fake or malformed file.")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("Could not open video file with OpenCV parser.")

    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if width <= 0 or height <= 0:
            raise ValueError("Invalid video frame dimensions.")
        if width > MAX_VIDEO_WIDTH or height > MAX_VIDEO_HEIGHT:
            raise ValueError(
                f"Video dimensions ({width}x{height}) exceed maximum allowed ({MAX_VIDEO_WIDTH}x{MAX_VIDEO_HEIGHT})."
            )
        if fps <= 0 or fps > 120:
            raise ValueError(f"Invalid video frame rate: {fps} fps.")
        if frame_count <= 0:
            raise ValueError("Video contains no readable frames.")
        if frame_count > MAX_VIDEO_FRAMES:
            raise ValueError(
                f"Video frame count ({frame_count}) exceeds maximum allowed ({MAX_VIDEO_FRAMES} frames)."
            )

        duration = frame_count / fps
        if duration > MAX_VIDEO_DURATION_SECONDS:
            raise ValueError(
                f"Video duration ({duration:.1f}s) exceeds maximum allowed ({MAX_VIDEO_DURATION_SECONDS}s)."
            )

        # Check decodability of the middle frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 2)
        ret, frame = cap.read()
        if not ret or frame is None:
            raise ValueError("Video frame decoding failed at representative frame.")

        return width, height, fps, frame_count
    finally:
        cap.release()


# --- 4. Model Integrity Verification (SEC-RES-01) ---
ALLOW_CUSTOM_UNPINNED_MODELS = (
    os.getenv("ALLOW_CUSTOM_UNPINNED_MODELS", "false").strip().lower() in ("true", "1")
)
CUSTOM_TRUSTED_MODEL_SHA256 = os.getenv("CUSTOM_TRUSTED_MODEL_SHA256", "").strip().lower()


def verify_model_integrity(model_path: Path) -> bool:
    """
    Verify SHA-256 integrity hash of a YOLO model file.
    If the model filename is in KNOWN_MODEL_HASHES, ensures hash matches.
    Custom/unpinned models are blocked by default to prevent arbitrary code execution
    via PyTorch pickle deserialization, unless explicitly allowed via ALLOW_CUSTOM_UNPINNED_MODELS
    or matching CUSTOM_TRUSTED_MODEL_SHA256.
    """
    if not model_path.is_file():
        return False
    name = model_path.name.lower()

    h = hashlib.sha256()
    with model_path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    actual_hash = h.hexdigest().lower()

    expected_hash = KNOWN_MODEL_HASHES.get(name)
    if expected_hash:
        if actual_hash != expected_hash:
            logger.error(
                "Model integrity check FAILED for pinned model '%s'! Expected %s, got %s.",
                name,
                expected_hash,
                actual_hash,
            )
            return False
        return True

    # Custom / unpinned weights handling
    trusted_custom_hash = os.getenv("CUSTOM_TRUSTED_MODEL_SHA256", CUSTOM_TRUSTED_MODEL_SHA256).strip().lower()
    if trusted_custom_hash:
        if actual_hash == trusted_custom_hash:
            logger.info("Custom model '%s' matches CUSTOM_TRUSTED_MODEL_SHA256 (%s).", name, actual_hash)
            return True
        logger.error(
            "Custom model '%s' SHA-256 (%s) does not match CUSTOM_TRUSTED_MODEL_SHA256 (%s).",
            name,
            actual_hash,
            trusted_custom_hash,
        )
        return False

    allow_custom = os.getenv("ALLOW_CUSTOM_UNPINNED_MODELS", "").strip().lower() in ("true", "1") or ALLOW_CUSTOM_UNPINNED_MODELS
    if not allow_custom:
        logger.error(
            "Security rejection: Model '%s' (SHA-256: %s) is unpinned. "
            "Loading unpinned PyTorch weights is prohibited by default to prevent deserialization vulnerabilities. "
            "Provide CUSTOM_TRUSTED_MODEL_SHA256 or set ALLOW_CUSTOM_UNPINNED_MODELS=true.",
            name,
            actual_hash,
        )
        return False

    logger.warning(
        "ALLOW_CUSTOM_UNPINNED_MODELS is enabled. Loading unpinned model '%s' (SHA-256: %s) with caution.",
        name,
        actual_hash,
    )
    return True


# --- 5. Rate Limiting (Token Bucket / Sliding Window & Process-Shared SQLite Backend - SEC-RES-04) ---
class SlidingWindowRateLimiter:
    """
    Thread-safe sliding-window rate limiter per client key (IP or session).
    """

    def __init__(self):
        self._history: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, client_key: str, max_requests: int, window_seconds: float) -> tuple[bool, int]:
        """
        Check if request is permitted.
        Returns (is_allowed, retry_after_seconds).
        """
        now = time.time()
        window_start = now - window_seconds

        with self._lock:
            timestamps = self._history.get(client_key, [])
            # Prune timestamps older than window
            valid_timestamps = [t for t in timestamps if t > window_start]

            if len(valid_timestamps) >= max_requests:
                earliest = valid_timestamps[0]
                retry_after = max(1, int(window_seconds - (now - earliest)))
                self._history[client_key] = valid_timestamps
                return False, retry_after

            valid_timestamps.append(now)
            self._history[client_key] = valid_timestamps
            return True, 0

    def cleanup(self):
        """Prune stale client entries."""
        now = time.time()
        with self._lock:
            stale_keys = [k for k, v in self._history.items() if not v or (now - v[-1]) > 3600]
            for k in stale_keys:
                del self._history[k]


class ProcessSharedRateLimiter:
    """
    Multi-process-safe rate limiter backed by an embedded SQLite database in WAL mode (SEC-RES-04).
    Ensures consistent rate-limiting across multiple Uvicorn workers and processes.
    Falls back gracefully to in-memory sliding window if disk database is unavailable.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (DATA_DIR / "data" / "rate_limits.sqlite3")
        self._fallback = SlidingWindowRateLimiter()
        self._use_fallback = False
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS rate_limits ("
                    "  key TEXT NOT NULL,"
                    "  timestamp REAL NOT NULL"
                    ");"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_rate_key_time ON rate_limits(key, timestamp);")
            secure_file_permissions(self.db_path)
            for extra in (
                self.db_path.with_name(self.db_path.name + "-wal"),
                self.db_path.with_name(self.db_path.name + "-shm"),
            ):
                if extra.is_file():
                    secure_file_permissions(extra)
        except Exception as e:
            logger.warning("Could not initialize SQLite rate limiter (%s). Falling back to in-memory: %s", self.db_path, e)
            self._use_fallback = True

    def is_allowed(self, client_key: str, max_requests: int, window_seconds: float) -> tuple[bool, int]:
        if self._use_fallback:
            return self._fallback.is_allowed(client_key, max_requests, window_seconds)

        now = time.time()
        window_start = now - window_seconds

        with self._lock:
            try:
                with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                    with conn:
                        conn.execute("DELETE FROM rate_limits WHERE key = ? AND timestamp < ?", (client_key, window_start))
                        cursor = conn.execute(
                            "SELECT timestamp FROM rate_limits WHERE key = ? ORDER BY timestamp ASC",
                            (client_key,),
                        )
                        rows = cursor.fetchall()

                        if len(rows) >= max_requests:
                            earliest = rows[0][0]
                            retry_after = max(1, int(window_seconds - (now - earliest)))
                            return False, retry_after

                        conn.execute("INSERT INTO rate_limits (key, timestamp) VALUES (?, ?)", (client_key, now))
                        return True, 0
            except Exception as e:
                logger.debug("Database error in rate limiter: %s. Using memory fallback.", e)
                return self._fallback.is_allowed(client_key, max_requests, window_seconds)

    def reset(self):
        with self._lock:
            self._fallback._history.clear()
            if not self._use_fallback:
                try:
                    with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                        with conn:
                            conn.execute("DELETE FROM rate_limits")
                except Exception:
                    pass

    @property
    def _history(self):
        class _HistoryProxy(dict):
            def __init__(proxy_self, parent):
                super().__init__()
                proxy_self._parent = parent

            def clear(proxy_self):
                proxy_self._parent.reset()
        return _HistoryProxy(self)

    def cleanup(self):
        if self._use_fallback:
            self._fallback.cleanup()
            return
        try:
            cutoff = time.time() - 3600
            with self._lock:
                with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                    with conn:
                        conn.execute("DELETE FROM rate_limits WHERE timestamp < ?", (cutoff,))
        except Exception:
            pass


GLOBAL_RATE_LIMITER = ProcessSharedRateLimiter()

# Default rate limits: (max_requests, window_seconds)
RATE_LIMIT_DEFAULTS = {
    "inference": (10, 60),    # 10 image/video analyses per minute
    "simulate": (30, 60),     # 30 simulations per minute
    "reports": (60, 60),      # 60 report operations per minute
    "general": (120, 60),     # 120 general requests per minute
}


# --- 6. Inference Concurrency Control ---
class InferenceConcurrencyManager:
    def __init__(self, max_concurrent: int = MAX_CONCURRENT_INFERENCES):
        self._semaphore = threading.Semaphore(max_concurrent)
        self._max = max_concurrent

    def acquire(self, timeout: float = 2.0) -> bool:
        return self._semaphore.acquire(timeout=timeout)

    def release(self):
        try:
            self._semaphore.release()
        except ValueError:
            pass


GLOBAL_INFERENCE_MANAGER = InferenceConcurrencyManager()


# --- 7. Atomic Report Persistence with Versioning & Audit History ---
_report_file_lock = threading.Lock()


def read_report_atomic(report_path: Path, max_retries: int = 5, backoff: float = 0.05) -> dict:
    """
    Safely reads a report with concurrency lock coordination and retry mechanism
    to prevent transient Windows file-locking collisions during rapid concurrent updates.
    """
    with _report_file_lock:
        for attempt in range(max_retries):
            try:
                return json.loads(report_path.read_text(encoding="utf-8"))
            except (PermissionError, json.JSONDecodeError):
                if attempt == max_retries - 1:
                    raise
                time.sleep(backoff * (attempt + 1))


def sanitize_junction_name(name: Optional[str]) -> str:
    """Sanitize and length-limit junction name."""
    if not name:
        return "Demo Junction"
    cleaned = re.sub(r'[\x00-\x1f\\/:\*\?"<>\|]', "", name).strip()
    return cleaned[:MAX_JUNCTION_NAME_LENGTH] or "Demo Junction"


def save_report_atomic(report: dict, report_dir: Path, source_channel: str = "api") -> dict:
    """
    Atomically writes the report JSON to disk using a temporary file and rename.
    Maintains revision history, timestamp, and modification audit metadata.
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    secure_file_permissions(report_dir)
    report_id = report.get("report_id")
    if not report_id or not str(report_id).isalnum():
        raise ValueError("Invalid or missing report_id.")

    target_path = report_dir / f"{report_id}.json"
    now_iso = datetime.now(timezone.utc).isoformat()

    with _report_file_lock:
        version = 1
        history: list[dict] = []

        if target_path.is_file():
            try:
                existing = json.loads(target_path.read_text(encoding="utf-8"))
                version = existing.get("version", 1) + 1
                history = existing.get("history", [])
                # Record the transition
                history.append({
                    "version": existing.get("version", 1),
                    "modified_at": now_iso,
                    "channel": source_channel,
                    "previous_counts": existing.get("counts"),
                    "previous_cycle": existing.get("cycle"),
                })
            except Exception as e:
                logger.warning("Could not read existing report for history tracking: %s", e)

        report["version"] = version
        report["last_modified_at"] = now_iso
        report["history"] = history[-20:]  # Keep latest 20 audit entries

        # Atomic write pattern: write to tmp file in same directory, flush, sync, replace
        temp_fd, temp_path = tempfile.mkstemp(dir=str(report_dir), prefix=f"tmp_{report_id}_", suffix=".json")
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, target_path)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    return report


# --- 8. Storage Accounting, Retention & Quota Enforcement (R4) ---
def _is_safe_path(base_dir: Path, target: Path) -> bool:
    try:
        resolved = target.resolve()
        return resolved.is_relative_to(base_dir.resolve())
    except Exception:
        return False


def calculate_storage_usage(dirs: Optional[list[Path]] = None) -> int:
    """
    Calculate actual file sizes in managed storage directories.
    Avoids counting directories, ignores external symlinks, and safely handles missing paths.
    """
    if dirs is None:
        dirs = [BASE_DIR / "uploads", BASE_DIR / "reports", BASE_DIR / "data"]

    total = 0
    for d in dirs:
        if not d.is_dir():
            continue
        try:
            for item in d.glob("*"):
                if not item.is_file() or item.name == ".gitkeep":
                    continue
                if item.is_symlink() and not _is_safe_path(d, item):
                    continue
                try:
                    total += item.stat().st_size
                except (OSError, FileNotFoundError):
                    pass
        except Exception as e:
            logger.debug("Error calculating storage in %s: %s", d, e)
    return total


class StorageManager:
    """
    Manages disk space accounting, concurrent reservations, and enforcement
    of the 500 MB application storage cap (R4).
    """

    def __init__(
        self,
        upload_dir: Optional[Path] = None,
        report_dir: Optional[Path] = None,
        max_bytes: int = MAX_STORAGE_BYTES,
    ):
        self.upload_dir = upload_dir or (DATA_DIR / "uploads")
        self.report_dir = report_dir or (DATA_DIR / "reports")
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._reservations: dict[str, int] = {}
        self._active_files: set[str] = set()

    def get_tracked_dirs(self) -> list[Path]:
        return [self.upload_dir, self.report_dir, DATA_DIR / "data"]

    def calculate_usage(self) -> int:
        return calculate_storage_usage(self.get_tracked_dirs())

    def get_status(self) -> dict:
        used = self.calculate_usage()
        with self._lock:
            reserved = sum(self._reservations.values())
        effective_used = min(self.max_bytes, used + reserved)
        available = max(0, self.max_bytes - effective_used)
        pct = round((used / self.max_bytes) * 100, 2) if self.max_bytes > 0 else 0.0

        uploads_count = 0
        if self.upload_dir.is_dir():
            uploads_count = sum(1 for p in self.upload_dir.glob("*") if p.is_file() and p.name != ".gitkeep")
        reports_count = 0
        if self.report_dir.is_dir():
            reports_count = sum(1 for p in self.report_dir.glob("*.json") if p.is_file())

        return {
            "total_used_bytes": used,
            "reserved_bytes": reserved,
            "max_allowed_bytes": self.max_bytes,
            "available_bytes": available,
            "usage_percentage": pct,
            "uploads_count": uploads_count,
            "reports_count": reports_count,
        }

    def reserve(self, amount_bytes: int) -> tuple[bool, Optional[str]]:
        """
        Attempt to reserve storage capacity before accepting or writing files.
        If capacity is insufficient, triggers automated storage cleanup.
        Returns (is_allowed, reservation_id).
        """
        if amount_bytes <= 0:
            return True, None
        if amount_bytes > self.max_bytes:
            return False, None

        with self._lock:
            current_used = self.calculate_usage()
            current_reserved = sum(self._reservations.values())

            if (current_used + current_reserved + amount_bytes) > self.max_bytes:
                # Trigger cleanup to free space
                cleanup_storage(
                    self.upload_dir,
                    self.report_dir,
                    target_free_bytes=amount_bytes,
                    active_files=self._active_files,
                    max_bytes=self.max_bytes,
                )
                current_used = self.calculate_usage()
                if (current_used + current_reserved + amount_bytes) > self.max_bytes:
                    logger.warning(
                        "Storage quota exceeded: requested %d bytes, current used %d, max %d",
                        amount_bytes, current_used, self.max_bytes,
                    )
                    return False, None

            res_id = secrets.token_hex(8)
            self._reservations[res_id] = amount_bytes
            return True, res_id

    def release(self, reservation_id: Optional[str]):
        if not reservation_id:
            return
        with self._lock:
            self._reservations.pop(reservation_id, None)

    def mark_active(self, filepath: Path):
        with self._lock:
            self._active_files.add(str(filepath.resolve()))

    def unmark_active(self, filepath: Path):
        with self._lock:
            self._active_files.discard(str(filepath.resolve()))


def cleanup_storage(
    upload_dir: Path,
    report_dir: Path,
    target_free_bytes: int = 0,
    active_files: Optional[set[str]] = None,
    max_bytes: int = MAX_STORAGE_BYTES,
) -> dict[str, Any]:
    """
    Cleans up expired uploads and reports according to retention policies,
    and evicts oldest eligible non-expired files if needed to enforce the 500 MB storage cap.
    Guarantees active processing files are never deleted.
    """
    active = active_files or set()
    now = time.time()
    upload_threshold = now - (UPLOAD_RETENTION_HOURS * 3600)
    report_threshold = now - (REPORT_RETENTION_HOURS * 3600)
    deleted_uploads = 0
    deleted_reports = 0
    freed_bytes = 0

    # 1. Clean expired uploads
    if upload_dir.is_dir():
        for item in upload_dir.glob("*"):
            if item.is_file() and item.name != ".gitkeep" and str(item.resolve()) not in active:
                try:
                    st = item.stat()
                    if st.st_mtime < upload_threshold:
                        size = st.st_size
                        item.unlink(missing_ok=True)
                        deleted_uploads += 1
                        freed_bytes += size
                except Exception as e:
                    logger.debug("Could not delete upload %s: %s", item, e)

    # 2. Clean expired reports
    if report_dir.is_dir():
        report_files = sorted(
            [p for p in report_dir.glob("*.json") if p.is_file() and str(p.resolve()) not in active],
            key=lambda p: p.stat().st_mtime,
        )
        for item in report_files:
            try:
                st = item.stat()
                if st.st_mtime < report_threshold:
                    size = st.st_size
                    item.unlink(missing_ok=True)
                    deleted_reports += 1
                    freed_bytes += size
            except Exception as e:
                logger.debug("Could not delete report %s: %s", item, e)

        # Enforce max report count
        remaining_reports = sorted(
            [p for p in report_dir.glob("*.json") if p.is_file() and str(p.resolve()) not in active],
            key=lambda p: p.stat().st_mtime,
        )
        if len(remaining_reports) > MAX_REPORTS_COUNT:
            excess = len(remaining_reports) - MAX_REPORTS_COUNT
            for item in remaining_reports[:excess]:
                try:
                    size = item.stat().st_size
                    item.unlink(missing_ok=True)
                    deleted_reports += 1
                    freed_bytes += size
                except Exception:
                    pass

    # 3. If storage still exceeds MAX_STORAGE_BYTES or target_free_bytes > 0:
    # Evict oldest uploads first
    current_total = calculate_storage_usage([upload_dir, report_dir, BASE_DIR / "data"])
    max_threshold = max_bytes - target_free_bytes
    if current_total > max_threshold and upload_dir.is_dir():
        candidate_uploads = sorted(
            [p for p in upload_dir.glob("*") if p.is_file() and p.name != ".gitkeep" and str(p.resolve()) not in active],
            key=lambda p: p.stat().st_mtime,
        )
        for item in candidate_uploads:
            if current_total <= max_threshold:
                break
            try:
                size = item.stat().st_size
                item.unlink(missing_ok=True)
                deleted_uploads += 1
                freed_bytes += size
                current_total -= size
            except Exception:
                pass

    return {
        "deleted_uploads": deleted_uploads,
        "deleted_reports": deleted_reports,
        "freed_bytes": freed_bytes,
        "current_usage_bytes": calculate_storage_usage([upload_dir, report_dir, BASE_DIR / "data"]),
    }


GLOBAL_STORAGE_MANAGER = StorageManager()
