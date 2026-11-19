from __future__ import annotations

import hmac
import json
import logging
import os
import queue
import shutil
import sys
import threading
import uuid
from pathlib import Path
from typing import Optional

# Add backend directory to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

from security_config import (
    ALLOWED_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    GLOBAL_STORAGE_MANAGER,
    MAX_JUNCTION_NAME_LENGTH,
    MAX_STORAGE_BYTES,
    MAX_UPLOAD_SIZE_BYTES,
    MAX_VIDEO_UPLOAD_SIZE_BYTES,
    MAX_VEHICLE_COUNT,
    cleanup_storage,
    read_report_atomic,
    sanitize_junction_name,
    save_report_atomic,
    secure_file_permissions,
    validate_image_file,
    validate_video_file,
    verify_magic_bytes,
)

if (BASE_DIR / ".env").is_file():
    secure_file_permissions(BASE_DIR / ".env")
from services.detection import (
    ModelUnavailableError,
    analyse_image,
    analyse_video,
    configure_pytorch_threads,
    get_detection_status,
    warmup_model,
)
from services.video_tracker import (
    analyse_multi_directional_videos,
)
from services.gemini import (
    GeminiAnalysisError,
    analyse_with_gemini,
    get_gemini_status,
)
from services.planning import (
    DEFAULT_ALL_RED_SECONDS,
    DEFAULT_GREEN_BUDGET,
    DEFAULT_YELLOW_SECONDS,
    DIRECTIONS,
    create_signal_plan,
)

UPLOAD_DIR = BASE_DIR / "uploads"
REPORT_DIR = BASE_DIR / "reports"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOGGER = logging.getLogger("ipc_worker")


def _save_report(report: dict) -> dict:
    return save_report_atomic(report, REPORT_DIR, source_channel="ipc")


def _validate_counts(counts: dict) -> dict[str, int]:
    if not isinstance(counts, dict) or set(counts.keys()) != set(DIRECTIONS):
        raise ValueError("Provide counts for North, South, East, and West.")
    cleaned = {}
    for d in DIRECTIONS:
        val = counts.get(d)
        if isinstance(val, bool):
            raise ValueError(f"Vehicle count for {d} cannot be a boolean.")
        if not isinstance(val, int) or val < 0:
            raise ValueError(f"Vehicle count for {d} must be a non-negative integer.")
        if val > MAX_VEHICLE_COUNT:
            raise ValueError(f"Vehicle count for {d} exceeds maximum limit of {MAX_VEHICLE_COUNT}.")
        cleaned[d] = val
    return cleaned


def handle_health(data: dict) -> dict:
    warmup_model(async_mode=True)
    det = get_detection_status()
    gem = get_gemini_status()
    return {
        "app": "urban_flow",
        "author": "Harsh Aggarwal",
        "copyright": "Copyright (c) 2026 Harsh Aggarwal. All rights reserved.",
        "status": "ok",
        "computer_vision_ready": det["computer_vision_ready"],
        "missing_dependencies": det.get("missing_dependencies", []),
        "model_available": det["model_available"],
        "model_name": det.get("model_name"),
        "gemini_available": gem["gemini_available"],
        "privacy_mode": "local_default",
        "storage": GLOBAL_STORAGE_MANAGER.get_status(),
    }


def handle_copyright(data: dict) -> dict:
    return {
        "project": "Urban Flow",
        "author": "Harsh Aggarwal",
        "email": "aggarwalharsh663@gmail.com",
        "copyright": "Copyright (c) 2026 Harsh Aggarwal. All rights reserved.",
        "license": "Urban Flow Proprietary License - Irrevocable Contributor IP Assignment",
        "terms": "All additions, modifications, or contributed files automatically vest sole copyright in Harsh Aggarwal.",
    }


def handle_simulate(data: dict) -> dict:
    counts = _validate_counts(data.get("counts", {}))
    raw_name = data.get("junction_name") or "Demo Junction"
    junction_name = sanitize_junction_name(raw_name)
    green_budget = max(40, min(600, int(data.get("green_budget", DEFAULT_GREEN_BUDGET))))
    yellow_seconds = max(1, min(10, int(data.get("yellow_seconds", DEFAULT_YELLOW_SECONDS))))
    all_red_seconds = max(0, min(10, int(data.get("all_red_seconds", DEFAULT_ALL_RED_SECONDS))))

    report = create_signal_plan(
        counts,
        junction_name=junction_name,
        source="simulated",
        green_budget=green_budget,
        yellow_seconds=yellow_seconds,
        all_red_seconds=all_red_seconds,
    )
    return _save_report(report)


def handle_calculate_signal_plan(data: dict) -> dict:
    counts = _validate_counts(data.get("counts", {}))
    raw_name = data.get("junction_name") or "Demo Junction"
    junction_name = sanitize_junction_name(raw_name)
    green_budget = max(40, min(600, int(data.get("green_budget", DEFAULT_GREEN_BUDGET))))
    yellow_seconds = max(1, min(10, int(data.get("yellow_seconds", DEFAULT_YELLOW_SECONDS))))
    all_red_seconds = max(0, min(10, int(data.get("all_red_seconds", DEFAULT_ALL_RED_SECONDS))))

    report = create_signal_plan(
        counts,
        junction_name=junction_name,
        green_budget=green_budget,
        yellow_seconds=yellow_seconds,
        all_red_seconds=all_red_seconds,
    )
    return _save_report(report)


# --- Safe File Handling & Source Protection (Issue #1) ---
WINDOWS_RESERVED_DEVICE_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})


def validate_source_path(file_path_str: str) -> Path:
    """
    Validate that file_path_str is a safe, existing, readable filesystem path.
    Rejects non-strings, empty paths, null bytes, Windows reserved devices,
    missing files, and non-regular files.
    """
    if not file_path_str or not isinstance(file_path_str, str):
        raise ValueError("file_path is required for analysis.")

    if "\0" in file_path_str:
        raise ValueError("Invalid file path: null characters detected.")

    try:
        raw_path = Path(file_path_str)
    except Exception as exc:
        raise ValueError(f"Invalid filesystem path: {exc}") from exc

    if raw_path.stem.upper() in WINDOWS_RESERVED_DEVICE_NAMES:
        raise ValueError(f"Invalid file path: reserved device name '{raw_path.stem}'.")

    try:
        resolved = raw_path.resolve(strict=True)
    except FileNotFoundError:
        raise FileNotFoundError(f"Source file not found: {file_path_str}")
    except PermissionError as exc:
        raise PermissionError(f"Permission denied accessing source file: {file_path_str}") from exc
    except OSError as exc:
        raise ValueError(f"Cannot access source file path: {exc}") from exc

    if not resolved.is_file():
        raise ValueError(f"Specified path is not a regular file: {file_path_str}")

    return resolved


def is_application_owned(path: Path) -> bool:
    """
    Check if a path is an internal application-owned file inside UPLOAD_DIR.
    A path is application-owned ONLY if:
    1. It exists as a regular file.
    2. Its canonical resolved path is strictly within UPLOAD_DIR.
    3. It is not a symlink pointing outside UPLOAD_DIR.
    """
    try:
        if not path or not path.is_file():
            return False
        resolved = path.resolve(strict=True)
        return resolved.is_relative_to(UPLOAD_DIR.resolve()) and not path.is_symlink()
    except Exception:
        return False


def safe_copy_to_upload_dir(
    src_path: Path,
    max_size_bytes: int = MAX_UPLOAD_SIZE_BYTES,
    cancellation_check: Optional[callable] = None,
) -> tuple[Path, str]:
    """
    Safely copy a source file into UPLOAD_DIR using an application-generated UUID name.

    Safety guarantees:
    - Original file src_path is opened read-only and is NEVER modified, moved, or deleted.
    - Pre-verifies available disk space before initiating the copy.
    - Writes to an isolated staging file (staging_<uuid>.tmp) inside UPLOAD_DIR.
    - Performs buffered chunk streaming (1 MB chunks) to protect against memory spikes.
    - Enforces maximum size bounds during transfer.
    - Flushes and fsyncs data to disk before atomic rename.
    - Cleans up partial staging files immediately if interrupted, cancelled, or on error.
    - Uses atomic replace to finalize to the destination path.
    - Applies restricted permissions (0o600 / owner read-write) to the destination.
    - Returns (dest_path, filename).
    """
    if not src_path or not src_path.is_file():
        raise FileNotFoundError(f"Source file not found: {src_path}")

    stat_info = src_path.stat()
    file_size = stat_info.st_size
    if file_size > max_size_bytes:
        raise ValueError(f"File exceeds maximum allowed size of {max_size_bytes // (1024 * 1024)} MB.")
    if file_size == 0:
        raise ValueError("Uploaded file is empty.")

    # Check available storage on disk (require file_size + 10MB safety cushion)
    disk_usage = shutil.disk_usage(UPLOAD_DIR)
    required_space = file_size + (10 * 1024 * 1024)
    if disk_usage.free < required_space:
        raise OSError(
            f"Insufficient disk space in upload storage: {disk_usage.free} bytes free, "
            f"{required_space} bytes required."
        )

    suffix = src_path.suffix.lower()
    dest_uuid = uuid.uuid4().hex
    filename = f"{dest_uuid}{suffix}"
    dest_path = UPLOAD_DIR / filename
    while dest_path.exists():
        dest_uuid = uuid.uuid4().hex
        filename = f"{dest_uuid}{suffix}"
        dest_path = UPLOAD_DIR / filename

    staging_path = UPLOAD_DIR / f"staging_{dest_uuid}.tmp"
    copied_bytes = 0

    try:
        if cancellation_check and cancellation_check():
            raise RuntimeError("Operation was cancelled before copying commenced.")

        with open(src_path, "rb") as fsrc, open(staging_path, "wb") as fdst:
            while True:
                if cancellation_check and cancellation_check():
                    raise RuntimeError("File copying was cancelled.")
                chunk = fsrc.read(1024 * 1024)  # 1 MB chunk
                if not chunk:
                    break
                copied_bytes += len(chunk)
                if copied_bytes > max_size_bytes:
                    raise ValueError(
                        f"File exceeds maximum allowed size of {max_size_bytes // (1024 * 1024)} MB."
                    )
                fdst.write(chunk)
            fdst.flush()
            os.fsync(fdst.fileno())

        # Verify copied size matches source size
        if copied_bytes != file_size:
            raise IOError(
                f"Copy verification failed: expected {file_size} bytes, wrote {copied_bytes} bytes."
            )

        secure_file_permissions(staging_path)

        # Atomic finalization
        staging_path.replace(dest_path)
        return dest_path, filename

    except Exception:
        staging_path.unlink(missing_ok=True)
        raise


def handle_analyse(data: dict, video: bool = False, req_id: Optional[str] = None) -> dict:
    file_path_str = data.get("file_path")
    src_path = validate_source_path(file_path_str)

    # Enforce maximum upload size before reading/copying (Finding 4, 12)
    file_size = src_path.stat().st_size
    max_size = MAX_UPLOAD_SIZE_BYTES
    if file_size > max_size:
        raise ValueError("File exceeds maximum allowed size of 100 MB.")
    if file_size == 0:
        raise ValueError("Uploaded file is empty.")

    # Enforce 500 MB application storage cap (R4)
    reserved, res_id = GLOBAL_STORAGE_MANAGER.reserve(file_size)
    if not reserved:
        raise ValueError("Storage quota exceeded (500 MB limit). Automatic cleanup could not free sufficient space.")

    dest_path: Optional[Path] = None
    try:
        GLOBAL_STORAGE_MANAGER.mark_active(src_path)

        suffix = src_path.suffix.lower()
        allowed = ALLOWED_VIDEO_EXTENSIONS if video else ALLOWED_IMAGE_EXTENSIONS
        if suffix not in allowed or suffix not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported file type '{suffix}'. Use: {', '.join(sorted(allowed))}")

        # Verify magic bytes on source file
        with src_path.open("rb") as f:
            header = f.read(32)
        if not verify_magic_bytes(header, suffix):
            raise ValueError(f"Magic bytes verification failed for '{suffix}'. File is invalid or spoofed.")

        # Validate image or video dimensions and decodability on source file
        if video:
            validate_video_file(src_path)
        else:
            validate_image_file(src_path)

        # Safely copy into UPLOAD_DIR with randomized UUID name (Issue #1: Never move or delete user's source file)
        dest_path, filename = safe_copy_to_upload_dir(
            src_path,
            max_size_bytes=max_size,
            cancellation_check=lambda: is_request_cancelled(req_id),
        )
        GLOBAL_STORAGE_MANAGER.mark_active(dest_path)

        if req_id and is_request_cancelled(req_id):
            raise RuntimeError(f"Request {req_id} was cancelled before inference.")

        green_budget = max(40, min(600, int(data.get("green_budget", DEFAULT_GREEN_BUDGET))))
        yellow_seconds = max(1, min(10, int(data.get("yellow_seconds", DEFAULT_YELLOW_SECONDS))))
        all_red_seconds = max(0, min(10, int(data.get("all_red_seconds", DEFAULT_ALL_RED_SECONDS))))
        raw_name = data.get("junction_name") or dest_path.stem.replace("_", " ").title()
        junction_name = sanitize_junction_name(raw_name)
        use_cloud_ai = bool(data.get("use_cloud_ai", False))

        result = None
        gemini_error = None

        # Finding 6: Local-only processing is default.
        # Cloud AI is only used if use_cloud_ai is True.
        if use_cloud_ai and get_gemini_status()["gemini_available"]:
            LOGGER.info("User requested cloud processing; attempting Gemini.")
            try:
                result = analyse_with_gemini(dest_path, UPLOAD_DIR, video)
            except (GeminiAnalysisError, ValueError) as error:
                gemini_error = error
                LOGGER.warning("Gemini analysis failed; falling back to local YOLO (%s)", error)

        if req_id and is_request_cancelled(req_id):
            raise RuntimeError(f"Request {req_id} was cancelled.")

        if result is None:
            result = analyse_video(dest_path, UPLOAD_DIR) if video else analyse_image(dest_path, UPLOAD_DIR)
            result["analysis_provider"] = "local-yolo"

        if req_id and is_request_cancelled(req_id):
            raise RuntimeError(f"Request {req_id} was cancelled.")

        report = create_signal_plan(
            result["counts"],
            junction_name=junction_name,
            source="video" if video else "image",
            original_url=f"/uploads/{filename}",
            annotated_url=f"/uploads/{result['annotated_filename']}",
            detection_count=result["total_count"],
            detections=result["detections"],
            analysis_note=result.get("analysis_note"),
            analysis_provider=result.get("analysis_provider"),
            green_budget=green_budget,
            yellow_seconds=yellow_seconds,
            all_red_seconds=all_red_seconds,
        )
        cleanup_storage(UPLOAD_DIR, REPORT_DIR)
        return _save_report(report)
    except Exception:
        # Clean up only application-owned working copy in UPLOAD_DIR on failure/cancellation
        if dest_path and dest_path.is_file():
            dest_path.unlink(missing_ok=True)
        # CRITICAL: Never delete or unlink src_path under any circumstances
        raise
    finally:
        GLOBAL_STORAGE_MANAGER.unmark_active(src_path)
        if dest_path:
            GLOBAL_STORAGE_MANAGER.unmark_active(dest_path)
        GLOBAL_STORAGE_MANAGER.release(res_id)


def handle_analyse_multi_video(data: dict, req_id: Optional[str] = None) -> dict:
    videos = data.get("videos") or {}
    if not isinstance(videos, dict) or not any(videos.values()):
        raise ValueError("At least one directional video must be provided for multi-video analysis.")

    total_size = 0
    src_paths: dict[str, Path] = {}
    dest_paths: dict[str, Path] = {}
    created_dest_files: list[Path] = []

    for dir_name, fpath_str in videos.items():
        if not fpath_str:
            continue
        norm_dir = dir_name.capitalize()
        if norm_dir not in DIRECTIONS:
            raise ValueError(f"Invalid direction: {dir_name}. Must be North, South, East, or West.")
        src = validate_source_path(fpath_str)
        size = src.stat().st_size
        if size > MAX_VIDEO_UPLOAD_SIZE_BYTES:
            raise ValueError(f"Video for {norm_dir} exceeds maximum allowed size of 150 MB.")
        if size == 0:
            raise ValueError(f"Video for {norm_dir} is empty.")
        suffix = src.suffix.lower()
        if suffix not in ALLOWED_VIDEO_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type '{suffix}' for {norm_dir}. Allowed: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
            )

        with src.open("rb") as f:
            header = f.read(32)
        if not verify_magic_bytes(header, suffix):
            raise ValueError(f"Magic bytes verification failed for {norm_dir} video ({suffix}).")

        src_paths[norm_dir] = src
        total_size += size

    reserved, res_id = GLOBAL_STORAGE_MANAGER.reserve(total_size)
    if not reserved:
        raise ValueError("Storage quota exceeded (500 MB limit). Automatic cleanup could not free sufficient space.")

    try:
        # Safely copy each directional video into UPLOAD_DIR
        for norm_dir, src in src_paths.items():
            dest, filename = safe_copy_to_upload_dir(
                src,
                max_size_bytes=MAX_VIDEO_UPLOAD_SIZE_BYTES,
                cancellation_check=lambda: is_request_cancelled(req_id),
            )
            created_dest_files.append(dest)
            dest_paths[norm_dir] = dest
            GLOBAL_STORAGE_MANAGER.mark_active(dest)

        if req_id and is_request_cancelled(req_id):
            raise RuntimeError(f"Request {req_id} was cancelled before inference.")

        green_budget = max(40, min(600, int(data.get("green_budget", DEFAULT_GREEN_BUDGET))))
        yellow_seconds = max(1, min(10, int(data.get("yellow_seconds", DEFAULT_YELLOW_SECONDS))))
        all_red_seconds = max(0, min(10, int(data.get("all_red_seconds", DEFAULT_ALL_RED_SECONDS))))
        raw_name = data.get("junction_name") or "Multi-Camera Junction"
        junction_name = sanitize_junction_name(raw_name)
        sample_fps = float(data.get("sample_fps", 2.0))

        result = analyse_multi_directional_videos(
            dest_paths,
            UPLOAD_DIR,
            cancellation_check=lambda: is_request_cancelled(req_id),
            sample_fps=sample_fps,
        )

        if req_id and is_request_cancelled(req_id):
            raise RuntimeError(f"Request {req_id} was cancelled.")

        report = create_signal_plan(
            result["counts"],
            junction_name=junction_name,
            source="multi_video",
            original_url=None,
            annotated_url=f"/uploads/{result['annotated_filename']}",
            detection_count=result["total_count"],
            detections=result["detections"],
            analysis_note=result.get("analysis_note"),
            analysis_provider=result.get("analysis_provider"),
            green_budget=green_budget,
            yellow_seconds=yellow_seconds,
            all_red_seconds=all_red_seconds,
        )
        report["directional_metrics"] = result.get("directional_metrics", {})
        report["annotated_files"] = result.get("annotated_files", {})
        report["original_files"] = {d: f"/uploads/{p.name}" for d, p in dest_paths.items() if p}
        cleanup_storage(UPLOAD_DIR, REPORT_DIR)
        return _save_report(report)
    except Exception:
        # Clean up only application-owned copies in UPLOAD_DIR on failure/cancellation
        for dest in created_dest_files:
            if dest and dest.is_file():
                dest.unlink(missing_ok=True)
        # CRITICAL: Never delete or unlink any src in src_paths under any circumstances
        raise
    finally:
        for dest in created_dest_files:
            GLOBAL_STORAGE_MANAGER.unmark_active(dest)
        GLOBAL_STORAGE_MANAGER.release(res_id)


def handle_get_report(data: dict) -> dict:
    report_id = str(data.get("report_id", ""))
    if not report_id.isalnum():
        raise ValueError("Invalid report ID.")
    report_path = REPORT_DIR / f"{report_id}.json"
    if not report_path.is_file():
        raise FileNotFoundError("Report not found.")
    return read_report_atomic(report_path)


def handle_update_cycle(data: dict) -> dict:
    report_id = str(data.get("report_id", ""))
    if not report_id.isalnum():
        raise ValueError("Invalid report ID.")
    report_path = REPORT_DIR / f"{report_id}.json"
    if not report_path.is_file():
        raise FileNotFoundError("Report not found.")

    report = read_report_atomic(report_path)
    green_budget = int(data.get("green_budget", report.get("cycle", {}).get("total_green_seconds", DEFAULT_GREEN_BUDGET)))
    yellow_seconds = int(data.get("yellow_seconds", report.get("cycle", {}).get("yellow_seconds_per_phase", DEFAULT_YELLOW_SECONDS)))
    all_red_seconds = int(data.get("all_red_seconds", report.get("cycle", {}).get("all_red_seconds_per_phase", DEFAULT_ALL_RED_SECONDS)))

    updated_report = create_signal_plan(
        report["counts"],
        junction_name=report["junction_name"],
        source=report["source"],
        original_url=report.get("original_url"),
        annotated_url=report.get("annotated_url"),
        detection_count=report.get("model_detection_count", report.get("total_vehicle_count")),
        detections=report.get("detections"),
        analysis_note=report.get("analysis_note"),
        analysis_provider=report.get("analysis_provider"),
        green_budget=green_budget,
        yellow_seconds=yellow_seconds,
        all_red_seconds=all_red_seconds,
    )
    updated_report["report_id"] = report_id
    updated_report["analysed_at"] = report["analysed_at"]
    return _save_report(updated_report)


def handle_update_counts(data: dict) -> dict:
    report_id = str(data.get("report_id", ""))
    if not report_id.isalnum():
        raise ValueError("Invalid report ID.")
    report_path = REPORT_DIR / f"{report_id}.json"
    if not report_path.is_file():
        raise FileNotFoundError("Report not found.")

    counts = _validate_counts(data.get("counts", {}))
    report = read_report_atomic(report_path)
    analysis_note = report.get("analysis_note") or ""
    review_note = "Directional counts were reviewed and corrected manually; the original detections are unchanged."
    if review_note not in analysis_note:
        analysis_note = f"{analysis_note.rstrip()} {review_note}".strip()

    green_budget = int(data.get("green_budget", report.get("cycle", {}).get("total_green_seconds", DEFAULT_GREEN_BUDGET)))
    yellow_seconds = int(data.get("yellow_seconds", report.get("cycle", {}).get("yellow_seconds_per_phase", DEFAULT_YELLOW_SECONDS)))
    all_red_seconds = int(data.get("all_red_seconds", report.get("cycle", {}).get("all_red_seconds_per_phase", DEFAULT_ALL_RED_SECONDS)))

    updated_report = create_signal_plan(
        counts,
        junction_name=report["junction_name"],
        source=report["source"],
        original_url=report.get("original_url"),
        annotated_url=report.get("annotated_url"),
        detection_count=report.get("model_detection_count", report.get("total_vehicle_count")),
        detections=report.get("detections"),
        analysis_note=analysis_note,
        analysis_provider=report.get("analysis_provider"),
        green_budget=green_budget,
        yellow_seconds=yellow_seconds,
        all_red_seconds=all_red_seconds,
    )
    updated_report["report_id"] = report_id
    updated_report["analysed_at"] = report["analysed_at"]
    return _save_report(updated_report)


# Cooperative Request Cancellation Registry (R6 & F12)
_cancel_lock = threading.Lock()
CANCELLED_REQUESTS: set[str] = set()


def cancel_request(cancel_id: str) -> None:
    """Register request cancellation in a thread-safe manner."""
    if cancel_id:
        with _cancel_lock:
            CANCELLED_REQUESTS.add(cancel_id)
        LOGGER.info("Registered cancellation for request ID: %s", cancel_id)


def is_request_cancelled(req_id: Optional[str]) -> bool:
    if not req_id:
        return False
    with _cancel_lock:
        return req_id in CANCELLED_REQUESTS


def pop_cancelled_request(req_id: Optional[str]) -> bool:
    if not req_id:
        return False
    with _cancel_lock:
        if req_id in CANCELLED_REQUESTS:
            CANCELLED_REQUESTS.remove(req_id)
            return True
        return False


def handle_directions(data: dict) -> dict:
    """Return available junction directions (read scope)."""
    return {"directions": list(DIRECTIONS)}


def handle_cancel(data: dict) -> dict:
    """Handle task cancellation request from Electron (R6)."""
    cancel_id = str(data.get("cancel_id", "")).strip()
    if cancel_id:
        cancel_request(cancel_id)
    return {"cancelled": cancel_id}


# --- IPC Worker Authentication & Action Scoping (U-02) ---
ACTION_REQUIRED_SCOPES = {
    "health": "read",
    "copyright": "read",
    "directions": "read",
    "get-report": "read",
    "simulate": "reports:write",
    "calculate-signal-plan": "reports:write",
    "signal-plan": "reports:write",
    "update-cycle": "reports:write",
    "update-counts": "reports:write",
    "analyse-image": "inference:write",
    "analyse-video": "inference:write",
    "analyse-multi-video": "inference:write",
    "cancel": "admin",
}


def get_expected_ipc_tokens() -> list[str]:
    """Retrieve expected session / API tokens from environment or security config."""
    tokens = []
    env_token = os.environ.get("URBAN_FLOW_IPC_TOKEN", "").strip()
    if env_token:
        tokens.append(env_token)
    try:
        from security_config import get_or_create_api_token
        master = get_or_create_api_token().strip()
        if master and master not in tokens:
            tokens.append(master)
    except Exception:
        pass
    return tokens


def verify_ipc_auth(req: dict) -> tuple[bool, str]:
    """
    Validate caller token using constant-time comparison and check required action scope (U-02, V-02).
    Returns (is_authorized, error_message).
    """
    action = req.get("action")
    required_scope = ACTION_REQUIRED_SCOPES.get(action)
    if not required_scope:
        return False, f"Unknown action: {action}"

    # Extract token from top-level or data payload
    token = req.get("token")
    if not token and isinstance(req.get("data"), dict):
        token = req["data"].get("token")

    if not token or not isinstance(token, str):
        return False, "Unauthorized: invalid IPC token or insufficient scope"

    token_str = token.strip()
    expected_tokens = get_expected_ipc_tokens()
    is_valid_token = False

    for exp in expected_tokens:
        if exp and hmac.compare_digest(token_str, exp):
            is_valid_token = True
            break

    # Also check against derived scoped tokens from security_config
    if not is_valid_token:
        try:
            from security_config import get_token_scopes
            scopes = get_token_scopes(token_str)
            if scopes and (required_scope in scopes or "admin" in scopes):
                is_valid_token = True
        except Exception:
            pass

    if not is_valid_token:
        return False, "Unauthorized: invalid IPC token or insufficient scope"

    # Verify scope attached to the request
    caller_scope = req.get("scope")
    if not caller_scope and isinstance(req.get("data"), dict):
        caller_scope = req["data"].get("scope")

    if caller_scope:
        if caller_scope != required_scope and caller_scope != "admin":
            return False, "Unauthorized: invalid IPC token or insufficient scope"

    return True, ""


HANDLERS = {
    "health": handle_health,
    "copyright": handle_copyright,
    "directions": handle_directions,
    "simulate": handle_simulate,
    "calculate-signal-plan": handle_calculate_signal_plan,
    "signal-plan": handle_calculate_signal_plan,
    "analyse-image": lambda d, req_id=None: handle_analyse(d, video=False, req_id=req_id),
    "analyse-video": lambda d, req_id=None: handle_analyse(d, video=True, req_id=req_id),
    "analyse-multi-video": lambda d, req_id=None: handle_analyse_multi_video(d, req_id=req_id),
    "get-report": handle_get_report,
    "update-cycle": handle_update_cycle,
    "update-counts": handle_update_counts,
    "cancel": handle_cancel,
}


def process_ipc_request(req: dict) -> dict:
    """
    Authenticate, validate action scope, and process a single IPC request (U-02).
    """
    req_id = req.get("id")
    action = req.get("action")
    data = req.get("data") or {}

    authorized, auth_err = verify_ipc_auth(req)
    if not authorized:
        LOGGER.warning("IPC request rejected: action=%s, reason=%s", action, auth_err)
        return {"id": req_id, "ok": False, "error": auth_err}

    if pop_cancelled_request(req_id):
        LOGGER.info("Skipping execution of pre-cancelled request: %s", req_id)
        return {"id": req_id, "ok": True, "result": {"cancelled": True}}

    handler = HANDLERS.get(action)
    if not handler:
        return {"id": req_id, "ok": False, "error": f"Unknown action: {action}"}

    try:
        if action in {"analyse-image", "analyse-video", "analyse-multi-video"}:
            result = handler(data, req_id=req_id)
        else:
            result = handler(data)

        if pop_cancelled_request(req_id):
            LOGGER.info("Discarding result of cancelled request: %s", req_id)
            return {"id": req_id, "ok": True, "result": {"cancelled": True}}

        return {"id": req_id, "ok": True, "result": result}
    except Exception as e:
        LOGGER.exception("Error processing request: %s", e)
        err_msg = str(e)
        err_msg = os.path.basename(err_msg) if ("\\" in err_msg or "/" in err_msg) else err_msg
        return {"id": req_id, "ok": False, "error": err_msg}


def main():
    # Centralized PyTorch thread configuration at startup to prevent oversubscription (Issue #5)
    try:
        configure_pytorch_threads()
    except Exception as exc:
        LOGGER.warning("Could not initialize centralized PyTorch thread settings: %s", exc)

    # Signal readiness to Electron
    print(json.dumps({"event": "ready", "app": "urban_flow"}), flush=True)
    warmup_model(async_mode=True)

    request_queue: queue.Queue[Optional[dict]] = queue.Queue()

    def _reader():
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line)
                    action = req.get("action")
                    if action == "cancel":
                        # W-02: Validate session credentials before executing cancellation in reader thread
                        is_auth, err_msg = verify_ipc_auth(req)
                        if not is_auth:
                            if req.get("id"):
                                print(json.dumps({"id": req.get("id"), "ok": False, "error": err_msg or "Unauthorized: invalid IPC token or insufficient scope"}), flush=True)
                            continue
                        handle_cancel(req.get("data") or {})
                        if req.get("id"):
                            print(json.dumps({"id": req.get("id"), "ok": True, "result": {"cancelled": True}}), flush=True)
                        continue
                    request_queue.put(req)
                except Exception as ex:
                    LOGGER.error("Failed to parse stdin line: %s", ex)
        finally:
            request_queue.put(None)

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    while True:
        req = request_queue.get()
        if req is None:
            break
        resp = process_ipc_request(req)
        print(json.dumps(resp), flush=True)


if __name__ == "__main__":
    main()
