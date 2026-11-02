from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path

# Add backend directory to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

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
    create_signal_plan,
)

UPLOAD_DIR = BASE_DIR / "uploads"
REPORT_DIR = BASE_DIR / "reports"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOGGER = logging.getLogger("ipc_worker")


def _save_report(report: dict) -> dict:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORT_DIR / f"{report['report_id']}.json"
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _validate_counts(counts: dict) -> dict[str, int]:
    if not isinstance(counts, dict) or set(counts.keys()) != set(DIRECTIONS):
        raise ValueError("Provide counts for North, South, East, and West.")
    for d in DIRECTIONS:
        val = counts.get(d)
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            raise ValueError(f"Vehicle count for {d} must be a non-negative integer.")
    return {direction: int(counts[direction]) for direction in DIRECTIONS}


def handle_health(data: dict) -> dict:
    return {
        "app": "urban_flow",
        "status": "ok",
        **get_detection_status(),
        **get_gemini_status(),
        "storage": "local",
    }


def handle_simulate(data: dict) -> dict:
    counts = _validate_counts(data.get("counts", {}))
    junction_name = data.get("junction_name") or "Demo Junction"
    green_budget = int(data.get("green_budget", DEFAULT_GREEN_BUDGET))
    yellow_seconds = int(data.get("yellow_seconds", DEFAULT_YELLOW_SECONDS))
    all_red_seconds = int(data.get("all_red_seconds", DEFAULT_ALL_RED_SECONDS))

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
    junction_name = data.get("junction_name") or "Demo Junction"
    green_budget = int(data.get("green_budget", DEFAULT_GREEN_BUDGET))
    yellow_seconds = int(data.get("yellow_seconds", DEFAULT_YELLOW_SECONDS))
    all_red_seconds = int(data.get("all_red_seconds", DEFAULT_ALL_RED_SECONDS))

    report = create_signal_plan(
        counts,
        junction_name=junction_name,
        green_budget=green_budget,
        yellow_seconds=yellow_seconds,
        all_red_seconds=all_red_seconds,
    )
    return _save_report(report)


def handle_analyse(data: dict, video: bool = False) -> dict:
    file_path_str = data.get("file_path")
    if not file_path_str:
        raise ValueError("file_path is required for analysis.")
    src_path = Path(file_path_str)
    if not src_path.is_file():
        raise FileNotFoundError(f"Source file not found: {file_path_str}")

    suffix = src_path.suffix.lower()
    allowed = {".mp4"} if video else {".jpg", ".jpeg", ".jpe", ".png"}
    if suffix not in allowed:
        raise ValueError(f"Unsupported file type '{suffix}'. Use: {', '.join(sorted(allowed))}")

    # Ensure file is saved in UPLOAD_DIR
    filename = f"{uuid.uuid4().hex}{suffix}"
    dest_path = UPLOAD_DIR / filename
    if src_path.resolve() != dest_path.resolve():
        dest_path.write_bytes(src_path.read_bytes())

    green_budget = int(data.get("green_budget", DEFAULT_GREEN_BUDGET))
    yellow_seconds = int(data.get("yellow_seconds", DEFAULT_YELLOW_SECONDS))
    all_red_seconds = int(data.get("all_red_seconds", DEFAULT_ALL_RED_SECONDS))
    junction_name = data.get("junction_name") or src_path.stem.replace("_", " ").title()

    result = None
    gemini_error = None
    if get_gemini_status()["gemini_available"]:
        try:
            result = analyse_with_gemini(dest_path, UPLOAD_DIR, video)
        except (GeminiAnalysisError, ValueError) as error:
            gemini_error = error
            LOGGER.warning("Gemini analysis failed; falling back to local YOLO (%s)", error)

    if result is None:
        result = analyse_video(dest_path, UPLOAD_DIR) if video else analyse_image(dest_path, UPLOAD_DIR)
        result["analysis_provider"] = "local-yolo"

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
    return _save_report(report)


def handle_get_report(data: dict) -> dict:
    report_id = data.get("report_id", "")
    if not report_id.isalnum():
        raise ValueError("Invalid report ID.")
    report_path = REPORT_DIR / f"{report_id}.json"
    if not report_path.is_file():
        raise FileNotFoundError("Report not found.")
    return json.loads(report_path.read_text(encoding="utf-8"))


def handle_update_cycle(data: dict) -> dict:
    report_id = data.get("report_id", "")
    if not report_id.isalnum():
        raise ValueError("Invalid report ID.")
    report_path = REPORT_DIR / f"{report_id}.json"
    if not report_path.is_file():
        raise FileNotFoundError("Report not found.")

    report = json.loads(report_path.read_text(encoding="utf-8"))
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
    report_id = data.get("report_id", "")
    if not report_id.isalnum():
        raise ValueError("Invalid report ID.")
    report_path = REPORT_DIR / f"{report_id}.json"
    if not report_path.is_file():
        raise FileNotFoundError("Report not found.")

    counts = _validate_counts(data.get("counts", {}))
    report = json.loads(report_path.read_text(encoding="utf-8"))
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


HANDLERS = {
    "health": handle_health,
    "simulate": handle_simulate,
    "calculate-signal-plan": handle_calculate_signal_plan,
    "analyse-image": lambda d: handle_analyse(d, video=False),
    "analyse-video": lambda d: handle_analyse(d, video=True),
    "get-report": handle_get_report,
    "update-cycle": handle_update_cycle,
    "update-counts": handle_update_counts,
}


def main():
    # Signal readiness to Electron
    print(json.dumps({"event": "ready", "app": "urban_flow"}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            req_id = req.get("id")
            action = req.get("action")
            data = req.get("data") or {}

            handler = HANDLERS.get(action)
            if not handler:
                resp = {"id": req_id, "ok": False, "error": f"Unknown action: {action}"}
            else:
                result = handler(data)
                resp = {"id": req_id, "ok": True, "result": result}
        except Exception as e:
            LOGGER.exception("Error processing request: %s", e)
            resp = {"id": req.get("id") if "req" in locals() and isinstance(req, dict) else None, "ok": False, "error": str(e)}

        print(json.dumps(resp), flush=True)


if __name__ == "__main__":
    main()
