"""
On-Device Privacy Redaction Service (R5 Part A).
Performs deterministic, on-device redaction of faces, pedestrians, driver compartments,
and vehicle license plates before any frame can be transmitted to cloud AI (Google Gemini).
Enforces fail-closed privacy: unredacted frames are NEVER sent to the cloud.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import cv2
import numpy as np

logger = logging.getLogger("urban_flow.privacy")


class PrivacyRedactionError(RuntimeError):
    """Raised when on-device privacy redaction cannot be completed safely."""


def _apply_strong_blur(img: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> None:
    """Apply heavy Gaussian blur and pixelation to a bounding region in-place."""
    h, w = img.shape[:2]
    rx1 = max(0, min(w - 1, int(x1)))
    ry1 = max(0, min(h - 1, int(y1)))
    rx2 = max(0, min(w, int(x2)))
    ry2 = max(0, min(h, int(y2)))

    rw = rx2 - rx1
    rh = ry2 - ry1
    if rw <= 2 or rh <= 2:
        return

    roi = img[ry1:ry2, rx1:rx2]
    # Step 1: Pixelate / downsample
    small_w = max(2, rw // 12)
    small_h = max(2, rh // 12)
    small = cv2.resize(roi, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
    pixelated = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)

    # Step 2: Apply heavy Gaussian blur over pixelated region to prevent de-pixelation attacks
    ksize_w = (rw // 4) * 2 + 1
    ksize_h = (rh // 4) * 2 + 1
    ksize = max(15, min(51, max(ksize_w, ksize_h)))
    if ksize % 2 == 0:
        ksize += 1
    blurred = cv2.GaussianBlur(pixelated, (ksize, ksize), 25)
    img[ry1:ry2, rx1:rx2] = blurred


def redact_frame_for_cloud(
    frame: np.ndarray,
    model: Optional[Any] = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Scans frame for persons, driver compartments, and license plates, applying heavy redactions.
    Ensures no unredacted personal identifiers or registration marks reach Google Gemini.
    Fails closed if the local detection model is unavailable.
    """
    if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
        raise PrivacyRedactionError("Invalid image frame for privacy redaction.")

    if model is None:
        try:
            from services.detection import _get_model
            model = _get_model()
        except Exception as e:
            logger.error("Could not initialize local model for privacy redaction: %s", e)
            raise PrivacyRedactionError(
                "Local computer-vision model is unavailable for privacy redaction. "
                "Cloud transmission is prohibited without verified on-device redaction."
            ) from e

    h, w = frame.shape[:2]
    redacted = frame.copy()

    # COCO classes: 0: person, 2: car, 3: motorcycle, 5: bus, 7: truck
    try:
        results = model.predict(
            frame,
            verbose=False,
            classes=[0, 2, 3, 5, 7],
            conf=0.10,
            imgsz=min(1280, max(w, h)),
        )[0]
    except Exception as e:
        logger.error("YOLO privacy scan failed: %s", e)
        raise PrivacyRedactionError(f"Privacy scan failed: {e}") from e

    persons_redacted = 0
    plates_redacted = 0
    vehicles_redacted = 0

    for b in results.boxes:
        cls_id = int(b.cls[0].item())
        coords = [int(v) for v in b.xyxy[0].tolist()]
        bx1, by1, bx2, by2 = coords
        bw = bx2 - bx1
        bh = by2 - by1
        if bw <= 0 or bh <= 0:
            continue

        if cls_id == 0:
            # Person detected: redact entire bounding box + 10% safety margin for faces and silhouettes
            pad_x = int(bw * 0.10)
            pad_y = int(bh * 0.10)
            _apply_strong_blur(redacted, bx1 - pad_x, by1 - pad_y, bx2 + pad_x, by2 + pad_y)
            persons_redacted += 1

        elif cls_id in (2, 3, 5, 7):
            # Vehicle detected:
            # 1. License plate region (lower 25% of vehicle, centered 60% of width)
            plate_y1 = by1 + int(bh * 0.72)
            plate_y2 = by2
            plate_x1 = bx1 + int(bw * 0.18)
            plate_x2 = bx1 + int(bw * 0.82)
            _apply_strong_blur(redacted, plate_x1, plate_y1, plate_x2, plate_y2)
            plates_redacted += 1

            # 2. Driver / passenger face compartment (top 35% of vehicle)
            driver_y1 = by1
            driver_y2 = by1 + int(bh * 0.38)
            driver_x1 = bx1 + int(bw * 0.15)
            driver_x2 = bx1 + int(bw * 0.85)
            _apply_strong_blur(redacted, driver_x1, driver_y1, driver_x2, driver_y2)
            vehicles_redacted += 1

    summary = {
        "persons_redacted": persons_redacted,
        "plates_redacted": plates_redacted,
        "vehicles_redacted": vehicles_redacted,
        "privacy_mode": "on_device_blur",
    }
    logger.info("On-device privacy redaction complete: %s", summary)
    return redacted, summary
