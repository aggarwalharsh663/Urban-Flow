from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel, Field

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
    DIRECTIONS,
    DEFAULT_GREEN_BUDGET,
    DEFAULT_YELLOW_SECONDS,
    DEFAULT_ALL_RED_SECONDS,
    calculate_green_times,
    create_signal_plan,
)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
UPLOAD_DIR = BASE_DIR / "uploads"
REPORT_DIR = BASE_DIR / "reports"
LOGGER = logging.getLogger(__name__)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Adaptive Traffic Signal System",
    description="Optional Gemini vision with local YOLO fallback and deterministic signal timing recommendations.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174", "http://127.0.0.1:5174", "http://localhost:8001", "http://127.0.0.1:8001"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


class CountsInput(BaseModel):
    junction_name: str = Field(default="Demo Junction", min_length=1, max_length=100)
    counts: dict[str, int]
    green_budget: int = Field(default=DEFAULT_GREEN_BUDGET, ge=40, le=600)
    yellow_seconds: int = Field(default=DEFAULT_YELLOW_SECONDS, ge=1, le=10)
    all_red_seconds: int = Field(default=DEFAULT_ALL_RED_SECONDS, ge=0, le=10)


class CycleUpdateInput(BaseModel):
    green_budget: int = Field(default=DEFAULT_GREEN_BUDGET, ge=40, le=600)
    yellow_seconds: int = Field(default=DEFAULT_YELLOW_SECONDS, ge=1, le=10)
    all_red_seconds: int = Field(default=DEFAULT_ALL_RED_SECONDS, ge=0, le=10)


def _validate_counts(counts: dict[str, int]) -> dict[str, int]:
    if set(counts) != set(DIRECTIONS):
        raise HTTPException(status_code=422, detail="Provide counts for North, South, East, and West.")
    if any(isinstance(value, bool) or value < 0 for value in counts.values()):
        raise HTTPException(status_code=422, detail="Vehicle counts must be non-negative integers.")
    return {direction: int(counts[direction]) for direction in DIRECTIONS}


def _save_report(report: dict) -> dict:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / f"{report['report_id']}.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


async def _store_upload(file: UploadFile, allowed: set[str]) -> tuple[Path, str]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Use: {', '.join(sorted(allowed))}.")
    filename = f"{uuid.uuid4().hex}{suffix}"
    destination = UPLOAD_DIR / filename
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 100 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Upload exceeds the 100 MB prototype limit.")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    if size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    return destination, filename


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        **get_detection_status(),
        **get_gemini_status(),
        "storage": "local",
    }


@app.post("/api/calculate-signal-plan")
def calculate_plan(payload: CountsInput) -> dict:
    counts = _validate_counts(payload.counts)
    return _save_report(create_signal_plan(
        counts,
        payload.junction_name,
        green_budget=payload.green_budget,
        yellow_seconds=payload.yellow_seconds,
        all_red_seconds=payload.all_red_seconds,
    ))


@app.post("/api/simulate")
def simulate(payload: CountsInput) -> dict:
    counts = _validate_counts(payload.counts)
    return _save_report(create_signal_plan(
        counts,
        payload.junction_name,
        source="simulated",
        green_budget=payload.green_budget,
        yellow_seconds=payload.yellow_seconds,
        all_red_seconds=payload.all_red_seconds,
    ))


async def _analyse(
    file: UploadFile,
    expected_suffixes: set[str],
    video: bool,
    junction_name: str | None,
    green_budget: int = DEFAULT_GREEN_BUDGET,
    yellow_seconds: int = DEFAULT_YELLOW_SECONDS,
    all_red_seconds: int = DEFAULT_ALL_RED_SECONDS,
) -> dict:
    path, filename = await _store_upload(file, expected_suffixes)
    result = None
    gemini_error = None
    if get_gemini_status()["gemini_available"]:
        try:
            result = analyse_with_gemini(path, UPLOAD_DIR, video)
        except (GeminiAnalysisError, ValueError) as error:
            gemini_error = error
            LOGGER.warning("Gemini analysis failed; falling back to local YOLO (%s).", error)

    try:
        if result is None:
            result = analyse_video(path, UPLOAD_DIR) if video else analyse_image(path, UPLOAD_DIR)
            result["analysis_provider"] = "local-yolo"
    except ModelUnavailableError as error:
        path.unlink(missing_ok=True)
        if gemini_error:
            raise HTTPException(
                status_code=503,
                detail=f"Gemini analysis failed and local YOLO is unavailable: {error}",
            ) from error
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Local analysis failed: {error}") from error

    report = create_signal_plan(
        result["counts"],
        junction_name=junction_name or Path(file.filename or "Uploaded junction").stem.replace("_", " ").title(),
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
    return _save_report(report)


@app.post("/api/analyse-image")
async def analyse_image_endpoint(
    file: Annotated[UploadFile, File(...)],
    junction_name: Annotated[str | None, Form()] = None,
    green_budget: Annotated[int, Form()] = DEFAULT_GREEN_BUDGET,
    yellow_seconds: Annotated[int, Form()] = DEFAULT_YELLOW_SECONDS,
    all_red_seconds: Annotated[int, Form()] = DEFAULT_ALL_RED_SECONDS,
) -> dict:
    return await _analyse(
        file,
        {".jpg", ".jpeg", ".jpe", ".png"},
        video=False,
        junction_name=junction_name,
        green_budget=green_budget,
        yellow_seconds=yellow_seconds,
        all_red_seconds=all_red_seconds,
    )


@app.post("/api/analyse-video")
async def analyse_video_endpoint(
    file: Annotated[UploadFile, File(...)],
    junction_name: Annotated[str | None, Form()] = None,
    green_budget: Annotated[int, Form()] = DEFAULT_GREEN_BUDGET,
    yellow_seconds: Annotated[int, Form()] = DEFAULT_YELLOW_SECONDS,
    all_red_seconds: Annotated[int, Form()] = DEFAULT_ALL_RED_SECONDS,
) -> dict:
    return await _analyse(
        file,
        {".mp4"},
        video=True,
        junction_name=junction_name,
        green_budget=green_budget,
        yellow_seconds=yellow_seconds,
        all_red_seconds=all_red_seconds,
    )


@app.get("/api/reports/{report_id}")
def get_report(report_id: str) -> dict:
    if not report_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid report ID.")
    report_path = REPORT_DIR / f"{report_id}.json"
    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="Report not found.")
    return json.loads(report_path.read_text(encoding="utf-8"))


@app.put("/api/reports/{report_id}/cycle")
def update_report_cycle(report_id: str, payload: CycleUpdateInput) -> dict:
    if not report_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid report ID.")
    report_path = REPORT_DIR / f"{report_id}.json"
    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="Report not found.")

    report = json.loads(report_path.read_text(encoding="utf-8"))
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
    return _save_report(updated_report)


@app.put("/api/reports/{report_id}/counts")
def update_report_counts(report_id: str, payload: CountsInput) -> dict:
    if not report_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid report ID.")
    report_path = REPORT_DIR / f"{report_id}.json"
    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="Report not found.")

    counts = _validate_counts(payload.counts)
    report = json.loads(report_path.read_text(encoding="utf-8"))
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
    return _save_report(updated_report)


@app.get("/api/directions")
def get_directions() -> dict:
    return {"directions": list(DIRECTIONS)}
