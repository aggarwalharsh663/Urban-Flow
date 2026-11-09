from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Annotated, Optional

from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from security_config import (
    ALL_SCOPES,
    ALLOWED_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    GLOBAL_INFERENCE_MANAGER,
    GLOBAL_RATE_LIMITER,
    GLOBAL_STORAGE_MANAGER,
    INFERENCE_TIMEOUT_SECONDS_IMAGE,
    INFERENCE_TIMEOUT_SECONDS_VIDEO,
    MAX_IMAGE_HEIGHT,
    MAX_IMAGE_WIDTH,
    MAX_JUNCTION_NAME_LENGTH,
    MAX_STORAGE_BYTES,
    MAX_UPLOAD_SIZE_BYTES,
    MAX_VEHICLE_COUNT,
    RATE_LIMIT_DEFAULTS,
    SCOPE_ADMIN,
    SCOPE_INFERENCE_WRITE,
    SCOPE_READ,
    SCOPE_REPORTS_WRITE,
    cleanup_storage,
    get_allowed_hosts,
    get_allowed_origins,
    get_token_scopes,
    read_report_atomic,
    sanitize_junction_name,
    save_report_atomic,
    secure_file_permissions,
    validate_image_file,
    validate_video_file,
    verify_api_token,
    verify_magic_bytes,
    verify_media_ticket,
    verify_token_scope,
)
from services.detection import (
    ModelUnavailableError,
    analyse_image,
    analyse_video,
    get_detection_status,
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
    calculate_green_times,
    create_signal_plan,
)

BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / ".env"
load_dotenv(env_path)
secure_file_permissions(env_path)
UPLOAD_DIR = BASE_DIR / "uploads"
REPORT_DIR = BASE_DIR / "reports"
LOGGER = logging.getLogger("urban_flow.backend")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Adaptive Traffic Signal System",
    description="Deterministic traffic signal timing recommendations with local YOLO and optional Gemini analysis.",
    version="1.0.0",
)

# 1. CORS Configuration (Finding 1: Explicit origins only, NO wildcard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)


# 2. Security Headers & CSRF / Origin Validation Middleware (Finding 1 & 9)
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # Host header validation for local server protection (R5 Part B)
    host_header = request.headers.get("host")
    if host_header:
        norm_host = host_header.strip().lower()
        if norm_host not in get_allowed_hosts():
            LOGGER.warning("Rejected request with unauthorized Host header: %s", host_header)
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Bad Request: Invalid Host header."},
            )

    # Origin verification for state-changing requests if Origin header is present
    if request.method in {"POST", "PUT", "DELETE"}:
        origin = request.headers.get("origin")
        if origin:
            allowed = get_allowed_origins()
            if origin not in allowed:
                LOGGER.warning("Rejected request with unauthorized origin: %s", origin)
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Forbidden: Request origin is not authorized."},
                )

    response = await call_next(request)

    # Inject security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; "
            "connect-src 'self'"
        )
    return response


# 3. Authentication & Scoped Authorization Dependencies (R1 & R2)
async def require_auth(
    request: Request,
    x_api_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
) -> str:
    """
    Enforces per-install token authentication.
    Accepts credentials strictly via protected request headers:
      1. X-API-Token header
      2. Authorization: Bearer <token>
    Query-string token authentication is completely removed from API endpoints (R2).
    """
    candidate = x_api_token
    if not candidate and authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            candidate = parts[1]

    if not candidate or not verify_api_token(candidate):
        LOGGER.warning("Authentication failure for %s %s from %s", request.method, request.url.path, request.client.host if request.client else "unknown")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return candidate


def require_scope(required_scope: str):
    """
    Enforces scoped authorization (R1).
    Validates that the presented token holds the required permission scope.
    """
    async def _check_scope(
        request: Request,
        token: Annotated[str, Depends(require_auth)],
    ) -> str:
        scopes = get_token_scopes(token)
        if required_scope not in scopes:
            LOGGER.warning("Token lacks required scope '%s' on %s", required_scope, request.url.path)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Token lacks required scope '{required_scope}'.",
            )
        return token
    return _check_scope


# 4. Rate Limiting Helper (Finding 5)
def enforce_rate_limit(request: Request, category: str = "general") -> None:
    client_ip = request.client.host if request.client else "127.0.0.1"
    max_reqs, window_sec = RATE_LIMIT_DEFAULTS.get(category, RATE_LIMIT_DEFAULTS["general"])
    allowed, retry_after = GLOBAL_RATE_LIMITER.is_allowed(f"{client_ip}:{category}", max_reqs, window_sec)
    if not allowed:
        LOGGER.warning("Rate limit exceeded for %s on %s (%s)", client_ip, request.url.path, category)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests for '{category}'. Please wait {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


# 5. Pydantic Models with Strict Input Validation (Finding 10)
class CountsInput(BaseModel):
    junction_name: str = Field(default="Demo Junction", min_length=1, max_length=100)
    counts: dict[str, int]
    green_budget: int = Field(default=DEFAULT_GREEN_BUDGET, ge=40, le=600)
    yellow_seconds: int = Field(default=DEFAULT_YELLOW_SECONDS, ge=1, le=10)
    all_red_seconds: int = Field(default=DEFAULT_ALL_RED_SECONDS, ge=0, le=10)

    @field_validator("counts", mode="before")
    @classmethod
    def validate_counts_dict(cls, val: Any) -> dict[str, int]:
        if not isinstance(val, dict) or set(val.keys()) != set(DIRECTIONS):
            raise ValueError("Counts must include North, South, East, and West.")
        cleaned = {}
        for d in DIRECTIONS:
            v = val[d]
            # Reject booleans explicitly (Pydantic int coercion prevention)
            if isinstance(v, bool):
                raise ValueError(f"Vehicle count for {d} cannot be a boolean.")
            if not isinstance(v, int) or v < 0:
                raise ValueError(f"Vehicle count for {d} must be a non-negative integer.")
            if v > MAX_VEHICLE_COUNT:
                raise ValueError(f"Vehicle count for {d} exceeds maximum limit of {MAX_VEHICLE_COUNT}.")
            cleaned[d] = v
        return cleaned

    @field_validator("junction_name")
    @classmethod
    def sanitize_name(cls, val: str) -> str:
        return sanitize_junction_name(val)


class CycleUpdateInput(BaseModel):
    green_budget: int = Field(default=DEFAULT_GREEN_BUDGET, ge=40, le=600)
    yellow_seconds: int = Field(default=DEFAULT_YELLOW_SECONDS, ge=1, le=10)
    all_red_seconds: int = Field(default=DEFAULT_ALL_RED_SECONDS, ge=0, le=10)


def _validate_counts(counts: dict[str, int]) -> dict[str, int]:
    if set(counts) != set(DIRECTIONS):
        raise HTTPException(status_code=422, detail="Provide counts for North, South, East, and West.")
    for d in DIRECTIONS:
        val = counts[d]
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            raise HTTPException(status_code=422, detail="Vehicle counts must be non-negative integers.")
        if val > MAX_VEHICLE_COUNT:
            raise HTTPException(status_code=422, detail=f"Vehicle count for {d} exceeds maximum limit of {MAX_VEHICLE_COUNT}.")
    return {direction: int(counts[direction]) for direction in DIRECTIONS}


# 6. Secure Upload Handling with Streaming, Magic Bytes & Size Limits (Findings 4, 7, 12)
async def _store_upload(file: UploadFile, allowed_suffixes: set[str]) -> tuple[Path, str]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed_suffixes or suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Use: {', '.join(sorted(allowed_suffixes))}.",
        )

    # Generate unpredictable UUID filename
    filename = f"{uuid.uuid4().hex}{suffix}"
    destination = UPLOAD_DIR / filename
    temp_destination = UPLOAD_DIR / f".tmp_{filename}"

    # Reserve initial capacity under 500 MB storage budget (R4)
    reserved, res_id = GLOBAL_STORAGE_MANAGER.reserve(min(MAX_UPLOAD_SIZE_BYTES, 10 * 1024 * 1024))
    if not reserved:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="Storage quota exceeded (500 MB limit reached). Automatic cleanup was unable to free enough space.",
        )

    size = 0
    header_bytes = bytearray()
    try:
        GLOBAL_STORAGE_MANAGER.mark_active(temp_destination)
        with temp_destination.open("wb") as output:
            while chunk := await file.read(64 * 1024):  # 64 KB chunks
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="Upload exceeds the 100 MB limit.",
                    )
                if GLOBAL_STORAGE_MANAGER.calculate_usage() + size > MAX_STORAGE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                        detail="Storage quota exceeded (500 MB limit reached).",
                    )
                if len(header_bytes) < 32:
                    header_bytes.extend(chunk[: 32 - len(header_bytes)])
                output.write(chunk)
                output.flush()

        if size == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded file is empty.")

        # Magic bytes verification
        if not verify_magic_bytes(bytes(header_bytes), suffix):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File content does not match expected format for {suffix}. Upload rejected.",
            )

        # Deep verification & dimension / duration bounding
        if suffix in ALLOWED_IMAGE_EXTENSIONS:
            try:
                validate_image_file(temp_destination)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        elif suffix in ALLOWED_VIDEO_EXTENSIONS:
            try:
                validate_video_file(temp_destination)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        # Atomically commit the validated upload file
        os.replace(temp_destination, destination)
    except Exception:
        temp_destination.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    finally:
        GLOBAL_STORAGE_MANAGER.unmark_active(temp_destination)
        GLOBAL_STORAGE_MANAGER.release(res_id)
        await file.close()

    return destination, filename


# 7. Secure Upload Serving Endpoint (R3, R2: Protected Media Serving)
@app.get("/uploads/{filename}")
async def serve_upload(
    filename: str,
    request: Request,
    x_api_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
    ticket: Annotated[Optional[str], Query()] = None,
):
    """
    Secure static upload file server (R3).
    Requires either:
      1. Header authentication (X-API-Token or Bearer token) with read scope, or
      2. Short-lived HMAC media ticket via query parameter for safe web <img> rendering (R2).
    """
    # Strict filename format check first: only media extensions are eligible (R3)
    pattern = r"^[a-zA-Z0-9_-]+(\.(jpg|jpeg|png|mp4))$"
    match = re.match(pattern, filename.lower())
    if not match:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")

    token = x_api_token
    if not token and authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]

    has_auth = bool(token and verify_token_scope(token, SCOPE_READ))
    has_ticket = bool(ticket and verify_media_ticket(filename, ticket))

    if not has_auth and not has_ticket:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Access to media requires valid authentication or a media ticket.",
        )

    file_path = (UPLOAD_DIR / filename).resolve()
    # Path containment check
    if not str(file_path).startswith(str(UPLOAD_DIR.resolve())):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")

    ext = match.group(1).lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".mp4": "video/mp4",
    }
    content_type = media_types.get(ext, "application/octet-stream")

    response = FileResponse(path=file_path, media_type=content_type)
    response.headers["Content-Disposition"] = f'inline; filename="{file_path.name}"'
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


# 8. API Endpoints

@app.get("/api/health")
def health(
    request: Request,
    x_api_token: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
) -> dict:
    """
    Health check endpoint (R3 & R4).
    Unauthenticated probes receive minimal status without disclosing internals.
    Authenticated requests receive complete diagnostics and safe storage metrics.
    """
    token = x_api_token
    if not token and authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]

    if not token or not verify_api_token(token):
        return {
            "app": "urban_flow",
            "status": "ok",
            "privacy_mode": "local_default",
            "storage": "local",
        }

    det = get_detection_status()
    gem = get_gemini_status()
    return {
        "app": "urban_flow",
        "status": "ok",
        "computer_vision_ready": det["computer_vision_ready"],
        "missing_dependencies": det.get("missing_dependencies", []),
        "model_available": det["model_available"],
        "model_name": det.get("model_name"),
        "gemini_available": gem["gemini_available"],
        "privacy_mode": "local_default",
        "storage": GLOBAL_STORAGE_MANAGER.get_status(),
    }


@app.post("/api/calculate-signal-plan")
def calculate_plan(
    payload: CountsInput,
    request: Request,
    auth_token: Annotated[str, Depends(require_scope(SCOPE_REPORTS_WRITE))],
) -> dict:
    enforce_rate_limit(request, category="simulate")
    counts = _validate_counts(payload.counts)
    report = create_signal_plan(
        counts,
        payload.junction_name,
        green_budget=payload.green_budget,
        yellow_seconds=payload.yellow_seconds,
        all_red_seconds=payload.all_red_seconds,
    )
    return save_report_atomic(report, REPORT_DIR, source_channel="api")


@app.post("/api/simulate")
def simulate(
    payload: CountsInput,
    request: Request,
    auth_token: Annotated[str, Depends(require_scope(SCOPE_REPORTS_WRITE))],
) -> dict:
    enforce_rate_limit(request, category="simulate")
    counts = _validate_counts(payload.counts)
    report = create_signal_plan(
        counts,
        payload.junction_name,
        source="simulated",
        green_budget=payload.green_budget,
        yellow_seconds=payload.yellow_seconds,
        all_red_seconds=payload.all_red_seconds,
    )
    return save_report_atomic(report, REPORT_DIR, source_channel="api")


async def _analyse(
    request: Request,
    file: UploadFile,
    expected_suffixes: set[str],
    video: bool,
    junction_name: str | None,
    green_budget: int = DEFAULT_GREEN_BUDGET,
    yellow_seconds: int = DEFAULT_YELLOW_SECONDS,
    all_red_seconds: int = DEFAULT_ALL_RED_SECONDS,
    use_cloud_ai: bool = False,
) -> dict:
    enforce_rate_limit(request, category="inference")

    # Concurrency control (Finding 5)
    acquired = GLOBAL_INFERENCE_MANAGER.acquire(timeout=2.0)
    if not acquired:
        LOGGER.warning("Inference capacity exhausted; rejected request.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inference capacity exhausted. Please retry in a few moments.",
        )

    path: Optional[Path] = None
    try:
        # Trigger storage cleanup routine safely (Finding 5)
        cleanup_storage(UPLOAD_DIR, REPORT_DIR)

        path, filename = await _store_upload(file, expected_suffixes)
        result = None
        gemini_error = None

        # Finding 6: Local-only processing is default.
        # Cloud AI only invoked if user explicitly opted in (use_cloud_ai=True) AND key configured.
        if use_cloud_ai and get_gemini_status()["gemini_available"]:
            LOGGER.info("User explicitly enabled cloud AI; requesting Gemini analysis.")
            try:
                result = await asyncio.to_thread(analyse_with_gemini, path, UPLOAD_DIR, video)
            except (GeminiAnalysisError, ValueError) as error:
                gemini_error = error
                LOGGER.warning("Gemini analysis failed; falling back to local YOLO (%s).", error)
        elif not use_cloud_ai and get_gemini_status()["gemini_available"]:
            LOGGER.info("Gemini key is configured, but local-only mode selected by user. Using YOLOv8.")

        # Local YOLO fallback or primary
        if result is None:
            timeout_sec = INFERENCE_TIMEOUT_SECONDS_VIDEO if video else INFERENCE_TIMEOUT_SECONDS_IMAGE
            try:
                fn = analyse_video if video else analyse_image
                result = await asyncio.wait_for(
                    asyncio.to_thread(fn, path, UPLOAD_DIR),
                    timeout=timeout_sec,
                )
                result["analysis_provider"] = "local-yolo"
            except asyncio.TimeoutError:
                if path:
                    path.unlink(missing_ok=True)
                LOGGER.error("Inference timed out after %ds", timeout_sec)
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail=f"Inference timed out after {timeout_sec} seconds.",
                )
            except ModelUnavailableError as error:
                if path:
                    path.unlink(missing_ok=True)
                LOGGER.error("YOLO model unavailable: %s", error)
                if gemini_error:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Cloud analysis failed and local YOLO model is unavailable.",
                    ) from error
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Local YOLO model is unavailable. Check model files.",
                ) from error
            except ValueError as error:
                if path:
                    path.unlink(missing_ok=True)
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
            except Exception as error:
                if path:
                    path.unlink(missing_ok=True)
                LOGGER.exception("Local inference processing error: %s", error)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Analysis failed due to an internal error. Please check server logs.",
                ) from error

        clean_jname = sanitize_junction_name(
            junction_name or Path(file.filename or "Uploaded junction").stem.replace("_", " ").title()
        )
        report = create_signal_plan(
            result["counts"],
            junction_name=clean_jname,
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
        return save_report_atomic(report, REPORT_DIR, source_channel="api")
    finally:
        GLOBAL_INFERENCE_MANAGER.release()


@app.post("/api/analyse-image")
async def analyse_image_endpoint(
    request: Request,
    auth_token: Annotated[str, Depends(require_scope(SCOPE_INFERENCE_WRITE))],
    file: Annotated[UploadFile, File(...)],
    junction_name: Annotated[str | None, Form()] = None,
    green_budget: Annotated[int, Form()] = DEFAULT_GREEN_BUDGET,
    yellow_seconds: Annotated[int, Form()] = DEFAULT_YELLOW_SECONDS,
    all_red_seconds: Annotated[int, Form()] = DEFAULT_ALL_RED_SECONDS,
    use_cloud_ai: Annotated[bool, Form()] = False,
) -> dict:
    return await _analyse(
        request=request,
        file=file,
        expected_suffixes=ALLOWED_IMAGE_EXTENSIONS,
        video=False,
        junction_name=junction_name,
        green_budget=green_budget,
        yellow_seconds=yellow_seconds,
        all_red_seconds=all_red_seconds,
        use_cloud_ai=use_cloud_ai,
    )


@app.post("/api/analyse-video")
async def analyse_video_endpoint(
    request: Request,
    auth_token: Annotated[str, Depends(require_scope(SCOPE_INFERENCE_WRITE))],
    file: Annotated[UploadFile, File(...)],
    junction_name: Annotated[str | None, Form()] = None,
    green_budget: Annotated[int, Form()] = DEFAULT_GREEN_BUDGET,
    yellow_seconds: Annotated[int, Form()] = DEFAULT_YELLOW_SECONDS,
    all_red_seconds: Annotated[int, Form()] = DEFAULT_ALL_RED_SECONDS,
    use_cloud_ai: Annotated[bool, Form()] = False,
) -> dict:
    return await _analyse(
        request=request,
        file=file,
        expected_suffixes=ALLOWED_VIDEO_EXTENSIONS,
        video=True,
        junction_name=junction_name,
        green_budget=green_budget,
        yellow_seconds=yellow_seconds,
        all_red_seconds=all_red_seconds,
        use_cloud_ai=use_cloud_ai,
    )


@app.get("/api/reports/{report_id}")
def get_report(
    report_id: str,
    request: Request,
    auth_token: Annotated[str, Depends(require_scope(SCOPE_READ))],
) -> dict:
    enforce_rate_limit(request, category="reports")
    if not report_id.isalnum():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid report ID.")
    report_path = REPORT_DIR / f"{report_id}.json"
    if not report_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    return read_report_atomic(report_path)


@app.put("/api/reports/{report_id}/cycle")
def update_report_cycle(
    report_id: str,
    payload: CycleUpdateInput,
    request: Request,
    auth_token: Annotated[str, Depends(require_scope(SCOPE_REPORTS_WRITE))],
) -> dict:
    enforce_rate_limit(request, category="reports")
    if not report_id.isalnum():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid report ID.")
    report_path = REPORT_DIR / f"{report_id}.json"
    if not report_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")

    report = read_report_atomic(report_path)
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
        green_budget=payload.green_budget,
        yellow_seconds=payload.yellow_seconds,
        all_red_seconds=payload.all_red_seconds,
    )
    updated_report["report_id"] = report_id
    updated_report["analysed_at"] = report["analysed_at"]
    return save_report_atomic(updated_report, REPORT_DIR, source_channel="api")


@app.put("/api/reports/{report_id}/counts")
def update_report_counts(
    report_id: str,
    payload: CountsInput,
    request: Request,
    auth_token: Annotated[str, Depends(require_scope(SCOPE_REPORTS_WRITE))],
) -> dict:
    enforce_rate_limit(request, category="reports")
    if not report_id.isalnum():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid report ID.")
    report_path = REPORT_DIR / f"{report_id}.json"
    if not report_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")

    counts = _validate_counts(payload.counts)
    report = read_report_atomic(report_path)
    analysis_note = report.get("analysis_note") or ""
    review_note = (
        "Directional counts were reviewed and corrected manually; the original detections are unchanged."
    )
    if review_note not in analysis_note:
        analysis_note = f"{analysis_note.rstrip()} {review_note}".strip()
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
        green_budget=payload.green_budget,
        yellow_seconds=payload.yellow_seconds,
        all_red_seconds=payload.all_red_seconds,
    )
    updated_report["report_id"] = report_id
    updated_report["analysed_at"] = report["analysed_at"]
    return save_report_atomic(updated_report, REPORT_DIR, source_channel="api")


@app.get("/api/directions")
def get_directions(
    request: Request,
    auth_token: Annotated[str, Depends(require_scope(SCOPE_READ))],
) -> dict:
    enforce_rate_limit(request, category="general")
    return {"directions": list(DIRECTIONS)}
