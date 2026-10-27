from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import cv2

from services.detection import DIRECTIONS, _write_annotated_frame, assign_direction

DEFAULT_MODEL = "gemini-3.8-flash"
REQUEST_TIMEOUT_SECONDS = 25
MAX_IMAGE_EDGE = 2048


class GeminiAnalysisError(RuntimeError):
    """Raised when the optional Gemini request or its response cannot be used."""


def get_gemini_status() -> dict:
    return {
        "gemini_available": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "gemini_model": os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
    }


def _response_schema() -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "detections": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "class": {
                            "type": "STRING",
                            "enum": ["car", "motorcycle", "bus", "truck"],
                        },
                        "box_2d": {
                            "type": "ARRAY",
                            "items": {"type": "INTEGER"},
                        },
                        "confidence": {"type": "NUMBER"},
                    },
                    "required": ["class", "box_2d", "confidence"],
                },
            },
        },
        "required": ["detections"],
    }


def _prepare_frame(frame):
    height, width = frame.shape[:2]
    scale = min(1.0, MAX_IMAGE_EDGE / max(height, width))
    if scale < 1:
        frame = cv2.resize(
            frame,
            (round(width * scale), round(height * scale)),
            interpolation=cv2.INTER_AREA,
        )
    success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not success:
        raise GeminiAnalysisError("The image could not be prepared for Gemini.")
    return frame, base64.b64encode(encoded).decode("ascii")


def _parse_detections(response: dict, width: int, height: int) -> list[dict]:
    try:
        text = response["candidates"][0]["content"]["parts"][0]["text"]
        payload = json.loads(text)
        raw_detections = payload["detections"]
        if not isinstance(raw_detections, list):
            raise TypeError("detections must be a list")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise GeminiAnalysisError("Gemini returned an unusable detection response.") from error

    detections = []
    for item in raw_detections:
        if not isinstance(item, dict) or item.get("class") not in {"car", "motorcycle", "bus", "truck"}:
            continue
        coordinates = item.get("box_2d")
        if not isinstance(coordinates, list) or len(coordinates) != 4:
            continue
        try:
            y1, x1, y2, x2 = [float(value) for value in coordinates]
            confidence = float(item["confidence"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(0 <= value <= 1000 for value in (y1, x1, y2, x2)):
            continue
        if not 0 <= confidence <= 1 or y2 <= y1 or x2 <= x1:
            continue

        box = [
            max(0, min(width - 1, round(x1 * width / 1000))),
            max(0, min(height - 1, round(y1 * height / 1000))),
            max(0, min(width - 1, round(x2 * width / 1000))),
            max(0, min(height - 1, round(y2 * height / 1000))),
        ]
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        detections.append({
            "class": item["class"],
            "direction": assign_direction(box, width, height),
            "confidence": round(confidence, 4),
            "box": box,
        })
    return detections


def _request_gemini(frame) -> list[dict]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiAnalysisError("Gemini is not configured.")

    model_name = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if not model_name.replace("-", "").replace(".", "").isalnum():
        raise GeminiAnalysisError("The configured Gemini model name is invalid.")
    original_height, original_width = frame.shape[:2]
    _, image_data = _prepare_frame(frame)
    prompt = (
        "Count every clearly visible road vehicle in this single junction image. "
        "Include only cars, motorcycles, buses, and trucks; do not count signs, road markings, "
        "or vehicle fragments. Return one tight bounding box per vehicle using box_2d "
        "coordinates [ymin, xmin, ymax, xmax] normalized from 0 to 1000, and a confidence "
        "from 0 to 1. Do not invent objects. Coordinates must surround the visible vehicle."
    )
    request_body = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_data}},
            ],
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _response_schema(),
            "temperature": 0,
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    request = urllib.request.Request(
        url,
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise GeminiAnalysisError(f"The Gemini API returned HTTP {error.code}.") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise GeminiAnalysisError("The Gemini request failed.") from error
    return _parse_detections(result, original_width, original_height)


def _read_frame(path: Path, video: bool):
    if not video:
        frame = cv2.imread(str(path))
        if frame is None:
            raise ValueError("OpenCV could not read this image. Try a valid JPG or PNG file.")
        return frame

    capture = cv2.VideoCapture(str(path))
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
    return frame


def analyse_with_gemini(path: Path, output_dir: Path, video: bool) -> dict:
    frame = _read_frame(path, video)
    detections = _request_gemini(frame)
    counts = {direction: 0 for direction in DIRECTIONS}
    for detection in detections:
        counts[detection["direction"]] += 1

    annotated_filename = f"{path.stem}-annotated.jpg"
    _write_annotated_frame(frame, detections, output_dir / annotated_filename)
    return {
        "counts": counts,
        "total_count": len(detections),
        "detections": detections,
        "annotated_filename": annotated_filename,
        "analysis_provider": "gemini",
        "analysis_note": (
            "Vehicle boxes were proposed by Gemini and direction counts were assigned "
            "deterministically from each box centre. The uploaded frame was sent to Google. "
            "Review all counts before using this prototype plan."
        ),
    }
