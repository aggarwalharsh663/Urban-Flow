from __future__ import annotations

import importlib.util
import logging
import math
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("urban_flow.detection")

MODEL_FILES = (
    "yolov8m.pt",
    "yolov8s.pt",
    "yolov8n.pt",
)
VEHICLE_CLASSES = {"car", "motorcycle", "bus", "truck"}
# COCO class IDs: 0: person, 2: car, 3: motorcycle, 5: bus, 7: truck, 67: cell phone
DETECTION_CLASS_IDS = [0, 2, 3, 5, 7, 67]
DIRECTIONS = ("North", "South", "East", "West")

# Direction colors in BGR format matching the frontend UI theme
DIRECTION_COLORS_BGR = {
    "North": (246, 130, 59),   # Blue (#3b82f6)
    "South": (247, 85, 168),   # Purple (#a855f7)
    "East": (11, 158, 245),    # Amber (#f59e0b)
    "West": (94, 197, 34),     # Green (#22c55e)
}

_model = None


class ModelUnavailableError(RuntimeError):
    """Raised when locally stored YOLO weights are not available."""


def _available_model_path() -> Path | None:
    backend_dir = Path(__file__).resolve().parents[1]
    return next(
        (backend_dir / filename for filename in MODEL_FILES if (backend_dir / filename).is_file()),
        None,
    )


def get_detection_status() -> dict:
    missing_dependencies = [
        package
        for package in ("cv2", "ultralytics")
        if importlib.util.find_spec(package) is None
    ]
    model_path = _available_model_path()
    return {
        "computer_vision_ready": not missing_dependencies,
        "missing_dependencies": missing_dependencies,
        "model_available": model_path is not None,
        "model_path": str(model_path) if model_path else None,
    }


def _get_model():
    global _model
    status = get_detection_status()
    if status["missing_dependencies"]:
        missing = ", ".join(status["missing_dependencies"])
        raise ModelUnavailableError(
            f"Image/video analysis needs missing Python packages: {missing}. "
            "Run backend\\setup.ps1, then restart the backend."
        )
    model_path = _available_model_path()
    if model_path is None:
        raise ModelUnavailableError(
            f"Local YOLO weights were not found in {Path(__file__).resolve().parents[1]}. "
            "Download yolov8m.pt, yolov8s.pt, or yolov8n.pt and place it in the backend folder; follow README.md."
        )
    if _model is None:
        from ultralytics import YOLO

        _model = YOLO(str(model_path))
    return _model


def _is_quad_cctv_grid(frame: np.ndarray) -> bool:
    """Detects whether an image is a 4-camera CCTV split screen (2x2 grid)."""
    h, w = frame.shape[:2]
    if h < 200 or w < 200:
        return False
    mid_x, mid_y = w // 2, h // 2
    var_x = min(float(np.var(frame[:, mid_x + d])) for d in range(-4, 5))
    var_y = min(float(np.var(frame[mid_y + d, :])) for d in range(-4, 5))
    return var_x < 60.0 and var_y < 60.0


def _intersection_over_union(first: list[int], second: list[int]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    if not intersection:
        return 0.0
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _is_duplicate_or_enclosed(first: list[int], second: list[int]) -> bool:
    """Checks whether two bounding boxes refer to the same physical vehicle."""
    if _intersection_over_union(first, second) > 0.40:
        return True

    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    if intersection == 0:
        return False

    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    smaller_area = min(first_area, second_area)
    return smaller_area > 0 and (intersection / smaller_area) > 0.65


def assign_direction(box: list[int], width: int, height: int, is_quad: bool = False, is_perspective: bool = False) -> str:
    """Assign approach direction for 4-camera CCTV layouts, perspective intersections, and aerial views."""
    cx = (box[0] + box[2]) / 2.0
    cy = (box[1] + box[3]) / 2.0

    if is_quad:
        # Standard CCTV 4-camera layout:
        # Top-Left: North, Top-Right: East, Bottom-Left: South, Bottom-Right: West
        if cy < height / 2.0:
            return "North" if cx < width / 2.0 else "East"
        else:
            return "South" if cx < width / 2.0 else "West"

    if is_perspective:
        # Perspective angled intersection: approach corridors match quadrants around the center junction
        # Top-Right: North, Top-Left: West, Bottom-Left: South, Bottom-Right: East
        cx0, cy0 = 0.47 * width, 0.52 * height
        dx = cx - cx0
        dy = cy - cy0
        if dy < 0:
            return "North" if dx > 0 else "West"
        else:
            return "East" if dx > 0 else "South"

    # Single aerial cross-intersection layout:
    dx = (cx - width / 2.0) / width
    dy = (cy - height / 2.0) / height
    if abs(dy) >= abs(dx):
        return "North" if dy < 0 else "South"
    else:
        return "East" if dx > 0 else "West"


def _write_annotated_frame(frame, detections: list[dict], output_path: Path) -> None:
    """Draw bounding boxes with directional color tags on frame and write to output_path."""
    annotated = frame.copy()
    for det in detections:
        x1, y1, x2, y2 = det["box"]
        direction = det["direction"]
        color = DIRECTION_COLORS_BGR.get(direction, (40, 210, 160))

        # Main bounding box
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

        # Label tag badge
        label = f"{det['class']} {det['confidence']:.0%} [{direction}]"
        (label_w, label_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        tag_y1 = max(0, y1 - label_h - 6) if y1 - label_h - 6 >= 0 else y1
        tag_y2 = tag_y1 + label_h + 6
        tag_x2 = min(frame.shape[1], x1 + label_w + 8)

        cv2.rectangle(annotated, (x1, tag_y1), (tag_x2, tag_y2), color, -1)
        cv2.putText(
            annotated,
            label,
            (x1 + 4, tag_y2 - baseline - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    if not cv2.imwrite(str(output_path), annotated):
        raise RuntimeError("Could not save the annotated frame.")


def _detect(frame: np.ndarray, output_dir: Path, filename: str) -> dict:
    height, width = frame.shape[:2]
    model = _get_model()
    is_grid = _is_quad_cctv_grid(frame)
    candidates = []
    total_pedestrians = 0

    if is_grid:
        # 4-camera CCTV layout:
        # Full-frame inference with road ROI perspective filtering
        full_res = model.predict(
            frame,
            verbose=False,
            classes=DETECTION_CLASS_IDS,
            conf=0.08,
            imgsz=1280,
        )[0]

        people = []
        for b in full_res.boxes:
            if int(b.cls[0].item()) == 0:
                people.append([int(v) for v in b.xyxy[0].tolist()])
        total_pedestrians = len(people)

        qw, qh = width / 2.0, height / 2.0
        for b in full_res.boxes:
            cls_id = int(b.cls[0].item())
            label = full_res.names[cls_id]
            conf = float(b.conf[0].item())

            # Never count pedestrians as vehicles
            if cls_id == 0:
                continue

            if label not in VEHICLE_CLASSES:
                continue

            coords = [int(v) for v in b.xyxy[0].tolist()]
            bw, bh = coords[2] - coords[0], coords[3] - coords[1]
            cx, cy = (coords[0] + coords[2]) / 2.0, (coords[1] + coords[3]) / 2.0

            # Local quadrant coordinates
            qx = cx if cx < qw else cx - qw
            qy = cy if cy < qh else cy - qh
            rel_x = qx / qw
            rel_y = qy / qh

            # Filter distant background / other road across intersection (rel_y < 0.38 or tiny box)
            # Allows capturing the full depth of queued traffic waiting at the intersection
            # while suppressing distant vehicles/pedestrians across the junction
            if rel_y < 0.38 or bh < 28 or bw < 32 or (bw * bh) < 1100:
                continue

            # Filter parked vehicles / sidewalks outside active road perspective trapezoid
            # Bounded to the roadway curb lines (rx: ~0.15 to ~0.83) to exclude sidewalk pedestrians
            # while accommodating curbside lanes and auto-rickshaws
            road_left = max(0.12, 0.20 - (rel_y - 0.50) * 0.25)
            road_right = min(0.83, 0.77 + (rel_y - 0.50) * 0.20)
            if rel_x < road_left or rel_x > road_right:
                continue

            # Suppress walking pedestrians misidentified as motorcycles/cars
            if any(_intersection_over_union(coords, p) > 0.40 for p in people):
                continue

            direction = assign_direction(coords, width, height, is_quad=True)

            candidates.append({
                "class": label,
                "direction": direction,
                "confidence": round(conf, 4),
                "box": coords,
            })

    else:
        # Single aerial intersection view:
        # High resolution multi-scale inference with sensitive detection for dark / small vehicles
        full_res = model.predict(
            frame,
            verbose=False,
            classes=DETECTION_CLASS_IDS,
            conf=0.10,
            imgsz=1280,
        )[0]

        for b in full_res.boxes:
            cls_id = int(b.cls[0].item())
            raw_label = full_res.names[cls_id]
            conf = float(b.conf[0].item())

            if cls_id == 0:
                total_pedestrians += 1
                continue

            # In overhead aerial views, rectangular cars are often classified as cell phone by COCO models
            if cls_id == 67:
                label = "car"
            elif raw_label in VEHICLE_CLASSES:
                label = raw_label
            else:
                continue

            coords = [int(v) for v in b.xyxy[0].tolist()]
            bw, bh = coords[2] - coords[0], coords[3] - coords[1]
            if bw < 14 or bh < 14 or (bw * bh) < 220:
                continue

            # In wide-angle perspective intersection views (e.g. 16:9 tilted perspective cameras),
            # filter out non-road areas: rooftop AC outdoor units and off-street parking stalls.
            # Direct orthogonal overhead intersection views (square 1:1 aspect ratio) remain completely untouched.
            is_perspective = (width / height) > 1.35
            if is_perspective:
                if (bw / width) < 0.022 or (bh / height) < 0.035:
                    continue

                cx = (coords[0] + coords[2]) / 2.0
                cy = (coords[1] + coords[3]) / 2.0
                nx = cx / width
                ny = cy / height

                # 1. Rooftop / AC compressor units on building
                if nx < 0.08 and ny < 0.40:
                    continue

                # 2. Bottom parking stalls (excludes the car parked at bottom)
                if 0.36 < nx < 0.60 and ny > 0.84:
                    continue

                # 3. Far right border boundary
                if nx > 0.96 and ny > 0.30:
                    continue

            direction = assign_direction(coords, width, height, is_quad=False, is_perspective=is_perspective)

            candidates.append({
                "class": label,
                "direction": direction,
                "confidence": round(conf, 4),
                "box": coords,
            })

    # Class-agnostic duplicate suppression
    accepted: list[dict] = []
    for cand in sorted(candidates, key=lambda item: item["confidence"], reverse=True):
        if any(_is_duplicate_or_enclosed(cand["box"], prev["box"]) for prev in accepted):
            continue
        accepted.append(cand)

    counts = {direction: 0 for direction in DIRECTIONS}
    for det in accepted:
        counts[det["direction"]] += 1

    _write_annotated_frame(frame, accepted, output_dir / filename)
    mode_text = "4-camera CCTV approach analysis" if is_grid else "aerial intersection analysis"
    ped_text = f" ({total_pedestrians} pedestrians and curbside parked vehicles excluded)" if total_pedestrians else ""
    return {
        "counts": counts,
        "total_count": len(accepted),
        "detections": accepted,
        "pedestrians_excluded": total_pedestrians,
        "analysis_note": (
            f"Local {Path(_available_model_path()).stem} detection optimized for {mode_text}{ped_text}."
        ),
    }


def analyse_image(image_path: Path, output_dir: Path) -> dict:
    _get_model()
    frame = cv2.imread(str(image_path))
    if frame is None:
        raise ValueError("OpenCV could not read this image. Try a valid JPG or PNG file.")
    annotated_filename = f"{image_path.stem}-annotated.jpg"
    result = _detect(frame, output_dir, annotated_filename)
    return {
        **result,
        "annotated_filename": annotated_filename,
        "analysis_note": (
            result["analysis_note"]
            if result["total_count"]
            else f"{result['analysis_note']} No supported vehicles were detected; try a clearer junction photo with unobstructed vehicles."
        ),
    }


def analyse_video(video_path: Path, output_dir: Path) -> dict:
    _get_model()
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError("OpenCV could not open this MP4 video.")
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = capture.get(cv2.CAP_PROP_FPS)
    if frame_count <= 0 or fps <= 0:
        capture.release()
        raise ValueError("The video does not contain readable frames.")

    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 2)
    success, frame = capture.read()
    capture.release()
    if not success:
        raise ValueError("Could not read a representative frame from the video.")

    annotated_filename = f"{video_path.stem}-annotated.jpg"
    result = _detect(frame, output_dir, annotated_filename)
    note = (
        "Video analysis uses a representative middle-frame snapshot; vehicles are not tracked across frames. "
        if result["total_count"]
        else "No supported vehicles were detected in the representative video frame. "
    )
    return {
        **result,
        "annotated_filename": annotated_filename,
        "analysis_note": note + result["analysis_note"],
    }
