"""
UrbanFlow - Multi-Directional Video Tracking & Temporal Analysis Engine.
Provides deterministic, lightweight IoU + Centroid multi-object tracking,
video safety bounds verification, and directional traffic demand estimation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

try:
    from security_config import (
        MAX_VEHICLE_COUNT,
        MAX_VIDEO_DURATION_SECONDS,
        MAX_VIDEO_FRAMES,
        MAX_VIDEO_HEIGHT,
        MAX_VIDEO_WIDTH,
        verify_magic_bytes,
    )
    from services.detection import (
        DETECTION_CLASS_IDS,
        DIRECTION_COLORS_BGR,
        _available_model_path,
        _get_model,
        _is_duplicate_or_enclosed,
        set_inference_priority,
    )
except ImportError:
    from backend.security_config import (
        MAX_VEHICLE_COUNT,
        MAX_VIDEO_DURATION_SECONDS,
        MAX_VIDEO_FRAMES,
        MAX_VIDEO_HEIGHT,
        MAX_VIDEO_WIDTH,
        verify_magic_bytes,
    )
    from backend.services.detection import (
        DETECTION_CLASS_IDS,
        DIRECTION_COLORS_BGR,
        _available_model_path,
        _get_model,
        _is_duplicate_or_enclosed,
        set_inference_priority,
    )

LOGGER = logging.getLogger("video_tracker")

# Video Analysis Configuration
DEFAULT_SAMPLE_FPS = 1.0  # Sample 1 frame per second for millisecond-level high-throughput tracking
MIN_VIDEO_DURATION_SECONDS = 2.0
MAX_VIDEO_DURATION_CAP = 120.0  # Support up to 120 seconds per direction
MAX_DECODED_PIXELS = 8_294_400  # 4K UHD (3840x2160)
MAX_TRACKER_TRACKS = 500
MAX_DISAPPEARED_FRAMES = 3  # ~3 seconds before track is dropped
MIN_DISPLACEMENT_PX = 25.0  # Pixel threshold to distinguish moving vs stationary vehicles

DIRECTIONS = ("North", "South", "East", "West")


def compute_iou(box1: list[int], box2: list[int]) -> float:
    """Compute Intersection-over-Union between two [x1, y1, x2, y2] bounding boxes."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    if intersection == 0:
        return 0.0

    area1 = max(0, box1[2] - box1[0]) * max(0, box1[3] - box1[1])
    area2 = max(0, box2[2] - box2[0]) * max(0, box2[3] - box2[1])
    union = area1 + area2 - intersection
    return float(intersection / union) if union > 0 else 0.0


@dataclass
class VehicleTrack:
    track_id: int
    label: str
    box: list[int]
    centroid: tuple[float, float]
    confidence: float
    first_seen_sec: float
    last_seen_sec: float
    initial_centroid: tuple[float, float]
    history: list[tuple[float, tuple[float, float]]] = field(default_factory=list)
    disappeared: int = 0
    total_displacement: float = 0.0
    is_stationary: bool = True
    is_cross_traffic: bool = False
    is_opposing: bool = False
    is_approach_target: bool = True


class CentroidIoUTracker:
    """
    Lightweight, deterministic multi-object tracker combining IoU and Euclidean
    centroid proximity. Features trajectory vector filtering to isolate monitored
    approach vehicles (queueing at red lights and discharging through the junction)
    from opposing-lane traffic and perpendicular cross-traffic.
    """

    def __init__(self, max_disappeared: int = MAX_DISAPPEARED_FRAMES, min_displacement: float = MIN_DISPLACEMENT_PX):
        self.next_track_id = 1
        self.tracks: dict[int, VehicleTrack] = {}
        self.retired_tracks: list[VehicleTrack] = []
        self.max_disappeared = max_disappeared
        self.min_displacement = min_displacement
        self.frame_peak_queue = 0
        self.queue_samples: list[int] = []
        self.frame_width = 1280
        self.frame_height = 720
        self.approach_corridor: Optional[tuple[float, float]] = None

    def update(self, detections: list[dict], timestamp_sec: float, frame_shape: tuple[int, int]) -> list[VehicleTrack]:
        """
        Update tracker with new detections from current sampled frame.
        detections format: list of dicts with 'box', 'class', 'confidence'
        """
        h, w = frame_shape[:2]
        self.frame_width = w
        self.frame_height = h
        diag = math.hypot(w, h)
        effective_min_disp = max(self.min_displacement, 0.025 * diag)

        if not detections:
            # Mark all active tracks as disappeared
            for tid in list(self.tracks.keys()):
                track = self.tracks[tid]
                track.disappeared += 1
                if track.disappeared > self.max_disappeared:
                    self.retired_tracks.append(track)
                    del self.tracks[tid]
            self.queue_samples.append(0)
            return list(self.tracks.values())

        det_centroids = []
        for det in detections:
            b = det["box"]
            cx = (b[0] + b[2]) / 2.0
            cy = (b[1] + b[3]) / 2.0
            det_centroids.append((cx, cy))

        # Count current frame queue (vehicles with low displacement / stationary)
        current_stationary = 0

        if not self.tracks:
            # Register all incoming detections as new tracks
            for i, det in enumerate(detections):
                if len(self.tracks) >= MAX_TRACKER_TRACKS:
                    break
                tid = self.next_track_id
                self.next_track_id += 1
                centroid = det_centroids[i]
                new_track = VehicleTrack(
                    track_id=tid,
                    label=det["class"],
                    box=det["box"],
                    centroid=centroid,
                    confidence=det["confidence"],
                    first_seen_sec=timestamp_sec,
                    last_seen_sec=timestamp_sec,
                    initial_centroid=centroid,
                    history=[(timestamp_sec, centroid)],
                    disappeared=0,
                    total_displacement=0.0,
                    is_stationary=True,
                    is_cross_traffic=False,
                    is_opposing=False,
                    is_approach_target=True,
                )
                self.tracks[tid] = new_track
                current_stationary += 1
            self.queue_samples.append(current_stationary)
            self.frame_peak_queue = max(self.frame_peak_queue, current_stationary)
            return list(self.tracks.values())

        # Match existing tracks to detections
        track_ids = list(self.tracks.keys())
        cost_matrix = []

        for tid in track_ids:
            tr = self.tracks[tid]
            row = []
            for i, det in enumerate(detections):
                iou = compute_iou(tr.box, det["box"])
                dist = math.hypot(tr.centroid[0] - det_centroids[i][0], tr.centroid[1] - det_centroids[i][1])
                norm_dist = dist / diag
                # Composite matching cost: high IoU and low distance produce low cost
                cost = (1.0 - iou) * 0.7 + min(1.0, norm_dist * 4.0) * 0.3
                row.append(cost)
            cost_matrix.append(row)

        matched_tracks = set()
        matched_dets = set()

        if cost_matrix:
            # Greedy bipartite assignment
            costs = np.array(cost_matrix)
            num_rows, num_cols = costs.shape

            while len(matched_tracks) < num_rows and len(matched_dets) < num_cols:
                min_idx = np.unravel_index(np.argmin(costs), costs.shape)
                row, col = int(min_idx[0]), int(min_idx[1])
                val = costs[row, col]
                if val > 0.85:  # Cost threshold beyond which association is rejected
                    break

                tid = track_ids[row]
                det = detections[col]
                centroid = det_centroids[col]

                # Update track
                tr = self.tracks[tid]
                tr.box = det["box"]
                tr.centroid = centroid
                tr.confidence = max(tr.confidence, det["confidence"])
                tr.last_seen_sec = timestamp_sec
                tr.disappeared = 0
                tr.history.append((timestamp_sec, centroid))

                # Update displacement from initial centroid
                dx = centroid[0] - tr.initial_centroid[0]
                dy = centroid[1] - tr.initial_centroid[1]
                tr.total_displacement = math.hypot(dx, dy)
                if tr.total_displacement >= effective_min_disp:
                    tr.is_stationary = False
                    # Detect cross traffic: motion vector has dominant horizontal movement
                    if abs(dx) > 1.6 * max(abs(dy), 1.0):
                        tr.is_cross_traffic = True
                        tr.is_approach_target = False

                if tr.is_stationary:
                    current_stationary += 1

                matched_tracks.add(row)
                matched_dets.add(col)
                costs[row, :] = 999.0
                costs[:, col] = 999.0

        # Handle unmatched detections (new vehicles entering scene)
        for col, det in enumerate(detections):
            if col not in matched_dets:
                if len(self.tracks) < MAX_TRACKER_TRACKS:
                    tid = self.next_track_id
                    self.next_track_id += 1
                    centroid = det_centroids[col]
                    new_track = VehicleTrack(
                        track_id=tid,
                        label=det["class"],
                        box=det["box"],
                        centroid=centroid,
                        confidence=det["confidence"],
                        first_seen_sec=timestamp_sec,
                        last_seen_sec=timestamp_sec,
                        initial_centroid=centroid,
                        history=[(timestamp_sec, centroid)],
                        disappeared=0,
                        total_displacement=0.0,
                        is_stationary=True,
                        is_cross_traffic=False,
                        is_opposing=False,
                        is_approach_target=True,
                    )
                    self.tracks[tid] = new_track
                    current_stationary += 1

        # Handle unmatched tracks (vehicles that left or are temporarily occluded)
        for row in range(len(track_ids)):
            if row not in matched_tracks:
                tid = track_ids[row]
                tr = self.tracks[tid]
                tr.disappeared += 1
                if tr.disappeared > self.max_disappeared:
                    self.retired_tracks.append(tr)
                    del self.tracks[tid]

        self.queue_samples.append(current_stationary)
        self.frame_peak_queue = max(self.frame_peak_queue, current_stationary)
        return list(self.tracks.values())

    def get_summary(self, video_duration_sec: float) -> dict:
        """
        Calculates directional traffic metrics filtered specifically for the
        monitored approach roadway (isolating queueing and discharging vehicles from
        opposing traffic across the median and cross-traffic through the intersection).
        """
        all_tracks = list(self.tracks.values()) + self.retired_tracks
        w = float(self.frame_width)
        h = float(self.frame_height)
        diag = math.hypot(w, h)
        effective_min_disp = max(self.min_displacement, 0.025 * diag)

        # 1. Identify cross-traffic from complete trajectory history
        for tr in all_tracks:
            dx = tr.centroid[0] - tr.initial_centroid[0]
            dy = tr.centroid[1] - tr.initial_centroid[1]
            disp = math.hypot(dx, dy)
            if disp >= effective_min_disp and abs(dx) > 1.3 * max(abs(dy), 1.0):
                tr.is_cross_traffic = True
                tr.is_approach_target = False

            # Exclude distant background beyond intersection horizon (y < 0.32 * h)
            if tr.centroid[1] < 0.32 * h:
                tr.is_opposing = True
                tr.is_approach_target = False

        # 2. Identify queued / stopping vehicles at the red light stop line
        queued_tracks = [tr for tr in all_tracks if tr.is_stationary and not tr.is_cross_traffic]

        # 3. Determine the monitored approach corridor (lateral bounds)
        if queued_tracks:
            q_xs = [tr.centroid[0] for tr in queued_tracks]
            corridor_min_x = min(q_xs)
            corridor_max_x = max(q_xs)
            span = corridor_max_x - corridor_min_x
            margin = max(0.08 * w, span * 0.3)
            corridor_x1 = max(0.0, corridor_min_x - margin)
            corridor_x2 = min(w, corridor_max_x + margin)
            self.approach_corridor = (corridor_x1, corridor_x2)
        else:
            non_cross = [tr for tr in all_tracks if not tr.is_cross_traffic]
            if non_cross:
                xs = [tr.centroid[0] for tr in non_cross]
                corridor_x1 = max(0.0, min(xs) - 0.05 * w)
                corridor_x2 = min(w, max(xs) + 0.05 * w)
                self.approach_corridor = (corridor_x1, corridor_x2)
            else:
                self.approach_corridor = (0.0, w)

        corridor_x1, corridor_x2 = self.approach_corridor

        # 4. Determine approach vertical flow direction
        moving_non_cross = [tr for tr in all_tracks if not tr.is_stationary and not tr.is_cross_traffic]
        sum_dy = 0.0
        for tr in moving_non_cross:
            dy = tr.centroid[1] - tr.initial_centroid[1]
            if abs(dy) >= effective_min_disp:
                sum_dy += (1.0 if dy > 0 else -1.0)

        dominant_flow_sign = 1.0 if sum_dy >= 0 else -1.0
        opposing_disp_thresh = max(self.min_displacement, 0.03 * diag)

        # 5. Filter opposing traffic across the median divider
        for tr in all_tracks:
            if tr.is_cross_traffic:
                continue

            dy = tr.centroid[1] - tr.initial_centroid[1]
            # If moving significantly in the reverse direction of approach flow
            if tr.total_displacement >= opposing_disp_thresh and (dy * dominant_flow_sign) < -opposing_disp_thresh:
                tr.is_opposing = True
                tr.is_approach_target = False
                continue

            # If vehicle centroid lies outside the monitored approach corridor
            cx = tr.centroid[0]
            if cx < (corridor_x1 - 0.04 * w) or cx > (corridor_x2 + 0.04 * w):
                tr.is_opposing = True
                tr.is_approach_target = False
                continue

            tr.is_approach_target = True

        # 6. Monitored approach tracks
        approach_tracks = [tr for tr in all_tracks if tr.is_approach_target and not tr.is_cross_traffic and not tr.is_opposing]

        # Graceful fallback: retain valid tracks if corridor filtering was overly strict
        if not approach_tracks:
            approach_tracks = [tr for tr in all_tracks if not tr.is_cross_traffic] or all_tracks

        total_unique = len(approach_tracks)
        moving_count = sum(1 for tr in approach_tracks if not tr.is_stationary)
        stationary_count = total_unique - moving_count

        avg_queue = float(np.mean(self.queue_samples)) if self.queue_samples else 0.0
        peak_queue = min(self.frame_peak_queue, total_unique) if total_unique > 0 else 0

        dur = max(video_duration_sec, 1.0)
        flow_rate_per_min = (total_unique / dur) * 60.0

        # Demand formula: 0.5 * PeakQueue + 0.3 * TotalUnique + 0.2 * FlowRatePerMin
        if total_unique == 0:
            demand = 0
        else:
            raw_demand = (0.5 * peak_queue) + (0.3 * total_unique) + (0.2 * flow_rate_per_min)
            demand = int(round(raw_demand))
            demand = max(1, min(MAX_VEHICLE_COUNT, demand))

        return {
            "unique_vehicles": total_unique,
            "moving_vehicles": moving_count,
            "stationary_vehicles": stationary_count,
            "peak_queue": peak_queue,
            "average_queue": round(avg_queue, 1),
            "flow_rate_per_min": round(flow_rate_per_min, 1),
            "duration_seconds": round(video_duration_sec, 1),
            "effective_demand": demand,
            "cross_traffic_filtered": sum(1 for tr in all_tracks if tr.is_cross_traffic),
            "opposing_traffic_filtered": sum(1 for tr in all_tracks if tr.is_opposing),
        }


def validate_directional_video(path: Path) -> tuple[int, int, float, int, float]:
    """
    Validates a video file against safety parameters:
    - Path safety and existence
    - Container magic bytes
    - Decodability via OpenCV
    - Resolution bounds (width <= 3840, height <= 2160, total pixels <= 8.3 MP)
    - FPS bounds (0 < fps <= 120)
    - Frame count bounds (0 < frames <= 7200)
    - Duration bounds (2.0s <= duration <= 120.0s)
    Returns: (width, height, fps, frame_count, duration)
    """
    if not path.is_file():
        raise ValueError(f"Video file does not exist: {path.name}")

    file_size = path.stat().st_size
    if file_size == 0:
        raise ValueError("Video file is empty (0 bytes).")

    with path.open("rb") as f:
        header = f.read(32)
    ext = path.suffix.lower()
    if not verify_magic_bytes(header, ext):
        raise ValueError(f"File magic signature does not match {ext} video container. Fake or corrupted file.")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("OpenCV could not open video container. Codec unsupported or corrupted.")

    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if width <= 0 or height <= 0:
            raise ValueError("Video contains invalid zero-dimension frames.")
        if width > 3840 or height > 2160 or (width * height) > MAX_DECODED_PIXELS:
            raise ValueError(f"Video resolution ({width}x{height}) exceeds safety limit (max 3840x2160 UHD).")
        if fps <= 0 or fps > 120.0:
            raise ValueError(f"Invalid frame rate ({fps} fps). Must be between 1 and 120 fps.")
        if frame_count <= 0:
            raise ValueError("Video contains no readable frames.")
        if frame_count > 7200:
            raise ValueError(f"Video frame count ({frame_count}) exceeds maximum allowed limit (7200 frames).")

        duration = frame_count / fps
        if duration < MIN_VIDEO_DURATION_SECONDS:
            raise ValueError(f"Video duration ({duration:.1f}s) is too short. Minimum duration is {MIN_VIDEO_DURATION_SECONDS}s.")
        if duration > MAX_VIDEO_DURATION_CAP:
            raise ValueError(f"Video duration ({duration:.1f}s) exceeds maximum 120s limit.")

        # Test frame reading at first frame and middle frame to detect container corruption
        ret, frame = cap.read()
        if not ret or frame is None:
            raise ValueError("Video initial frame decode failed. File is truncated or malformed.")

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 2)
        ret, frame = cap.read()
        if not ret or frame is None:
            raise ValueError("Video middle frame decode failed. File is truncated or corrupted.")

        return width, height, fps, frame_count, duration
    finally:
        cap.release()


def analyse_directional_video_clip(
    video_path: Path,
    direction: str,
    output_dir: Path,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    cancellation_check: Optional[Callable[[], bool]] = None,
) -> dict:
    """
    Process a single directional video clip with hardware-accelerated batching:
    - Extracts sampled frames via fast frame seeking
    - Runs vectorized batch YOLO vehicle detection at native 640px resolution
    - Tracks vehicles over time with CentroidIoUTracker
    - Outputs annotated representative frame with track overlays
    - Calculates flow rate, peak queue, and effective directional demand in milliseconds
    """
    norm_dir = direction.capitalize()
    if norm_dir not in DIRECTIONS:
        raise ValueError(f"Invalid direction '{direction}'. Must be one of: {', '.join(DIRECTIONS)}")

    width, height, native_fps, frame_count, duration = validate_directional_video(video_path)

    model = _get_model()
    set_inference_priority()
    try:
        import os
        import torch
        torch.set_num_threads(min(12, os.cpu_count() or 4))
    except Exception:
        pass

    tracker = CentroidIoUTracker()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path.name}")

    frame_interval = max(1, int(round(native_fps / sample_fps)))
    target_indices = list(range(0, frame_count, frame_interval))
    if not target_indices:
        target_indices = [0]

    sampled_frames = []
    sampled_timestamps = []
    mid_target_idx = frame_count // 2
    best_mid_diff = float("inf")
    rep_frame_idx = 0

    try:
        for f_idx in target_indices:
            if cancellation_check and cancellation_check():
                raise RuntimeError(f"Video processing cancelled during {norm_dir} analysis.")

            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            sampled_frames.append(frame)
            sampled_timestamps.append(f_idx / native_fps)

            diff = abs(f_idx - mid_target_idx)
            if diff < best_mid_diff:
                best_mid_diff = diff
                rep_frame_idx = len(sampled_frames) - 1
    finally:
        cap.release()

    if not sampled_frames:
        raise ValueError("Could not extract any valid sampled frames from the video.")

    # Vectorized batch YOLO inference (640px native dimension for maximum SIMD throughput)
    batch_size = 16
    all_res = []
    for b_start in range(0, len(sampled_frames), batch_size):
        if cancellation_check and cancellation_check():
            raise RuntimeError(f"Video processing cancelled during {norm_dir} analysis.")
        b_frames = sampled_frames[b_start : b_start + batch_size]
        res_chunk = model.predict(
            b_frames,
            verbose=False,
            classes=DETECTION_CLASS_IDS,
            conf=0.18,
            imgsz=640,
            batch=len(b_frames),
        )
        all_res.extend(res_chunk)

    representative_frame = sampled_frames[rep_frame_idx].copy()
    all_detections_for_viz = []

    for idx, (res, timestamp_sec, frame) in enumerate(zip(all_res, sampled_timestamps, sampled_frames)):
        frame_candidates = []
        for b in res.boxes:
            cls_id = int(b.cls[0].item())
            label = res.names[cls_id]
            conf = float(b.conf[0].item())
            box = [int(v) for v in b.xyxy[0].tolist()]

            # Avoid pedestrians (class 0)
            if cls_id == 0:
                continue

            # Filter distant background clutter across the junction horizon (y < 0.32 * height)
            cy = (box[1] + box[3]) / 2.0
            if cy < 0.32 * height:
                continue

            # Filter extreme aspect ratios (e.g. power lines or pavement markings)
            bw = box[2] - box[0]
            bh = box[3] - box[1]
            if bw <= 12 or bh <= 12:
                continue
            aspect = bw / float(bh)
            if aspect < 0.25 or aspect > 4.5:
                continue

            frame_candidates.append({
                "box": box,
                "class": label,
                "confidence": conf,
                "direction": norm_dir,
            })

        # Suppress duplicates
        accepted_frame_dets = []
        for cand in sorted(frame_candidates, key=lambda item: item["confidence"], reverse=True):
            if any(_is_duplicate_or_enclosed(cand["box"], prev["box"]) for prev in accepted_frame_dets):
                continue
            accepted_frame_dets.append(cand)

        # Update tracker
        active_tracks = tracker.update(accepted_frame_dets, timestamp_sec, frame.shape)

        if idx == rep_frame_idx:
            all_detections_for_viz = accepted_frame_dets

    summary = tracker.get_summary(duration)

    # Filter visualizer detections to show strictly monitored approach vehicles
    # (matching verified tracks queueing at red lights or discharging through the intersection)
    all_tracks = list(tracker.tracks.values()) + tracker.retired_tracks
    approach_tracks = [tr for tr in all_tracks if not tr.is_cross_traffic and not tr.is_opposing]

    approach_detections_for_viz = []
    for det in all_detections_for_viz:
        cx = (det["box"][0] + det["box"][2]) / 2.0
        cy = (det["box"][1] + det["box"][3]) / 2.0
        matched = False
        for tr in approach_tracks:
            if compute_iou(det["box"], tr.box) > 0.25 or (abs(cx - tr.centroid[0]) < 65 and abs(cy - tr.centroid[1]) < 65):
                matched = True
                break
        if matched:
            approach_detections_for_viz.append(det)

    if not approach_detections_for_viz:
        approach_detections_for_viz = [d for d in all_detections_for_viz if ((d["box"][1] + d["box"][3]) / 2.0) >= 0.32 * height] or all_detections_for_viz

    # Generate annotated frame with directional tags and track stats
    annotated_filename = f"{video_path.stem}-{norm_dir.lower()}-annotated.jpg"
    annotated_path = output_dir / annotated_filename
    _write_video_annotated_frame(representative_frame, approach_detections_for_viz, norm_dir, summary, annotated_path)

    return {
        "direction": norm_dir,
        "metrics": summary,
        "effective_demand": summary["effective_demand"],
        "annotated_filename": annotated_filename,
        "sampled_frames": len(sampled_frames),
        "detections": approach_detections_for_viz,
    }


def _write_video_annotated_frame(
    frame: np.ndarray,
    detections: list[dict],
    direction: str,
    summary: dict,
    output_path: Path,
) -> None:
    """Renders monitored approach vehicles with directional badges and video flow metrics overlay."""
    annotated = frame.copy()
    color = DIRECTION_COLORS_BGR.get(direction, (40, 210, 160))

    for det in detections:
        x1, y1, x2, y2 = det["box"]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = f"{det['class']} [{direction} Approach]"
        (label_w, label_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        tag_y1 = max(0, y1 - label_h - 6)
        cv2.rectangle(annotated, (x1, tag_y1), (min(frame.shape[1], x1 + label_w + 8), tag_y1 + label_h + 6), color, -1)
        cv2.putText(
            annotated,
            label,
            (x1 + 4, tag_y1 + label_h + 1),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    # Add HUD information bar at top of frame
    hud_text = (
        f"Approach: {direction.upper()} | Monitored: {summary['unique_vehicles']} | "
        f"Peak Queue: {summary['peak_queue']} | Flow: {summary['flow_rate_per_min']}/min | "
        f"Demand: {summary['effective_demand']}"
    )
    (tw, th), tb = cv2.getTextSize(hud_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(annotated, (0, 0), (annotated.shape[1], th + 16), (20, 24, 33), -1)
    cv2.putText(annotated, hud_text, (10, th + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1, cv2.LINE_AA)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), annotated):
        raise RuntimeError(f"Could not write annotated video frame to {output_path}")


def analyse_multi_directional_videos(
    directional_paths: dict[str, Optional[Path]],
    output_dir: Path,
    cancellation_check: Optional[Callable[[], bool]] = None,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
) -> dict:
    """
    Coordinates multi-video directional traffic analysis across North, South, East, West.
    Utilizes concurrent multi-threading across CPU cores to process all camera approaches
    in parallel, reducing end-to-end processing time to milliseconds.
    Supports partial uploads with graceful fallback: missing directions are assigned
    zero vehicle demand floor (giving minimum green clearance).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    directional_results = {}
    directional_demands = {d: 0 for d in DIRECTIONS}
    directional_metrics = {}
    combined_detections = []
    total_unique_all_directions = 0
    annotated_files = {}

    provided_approaches = {}
    for d in DIRECTIONS:
        vpath = directional_paths.get(d) or directional_paths.get(d.lower())
        if vpath and Path(vpath).is_file():
            provided_approaches[d] = Path(vpath)
        else:
            LOGGER.info("No video provided for approach: %s (Applying baseline minimum floor)", d)
            directional_demands[d] = 0
            directional_metrics[d] = {
                "unique_vehicles": 0,
                "moving_vehicles": 0,
                "stationary_vehicles": 0,
                "peak_queue": 0,
                "average_queue": 0.0,
                "flow_rate_per_min": 0.0,
                "duration_seconds": 0.0,
                "effective_demand": 0,
                "note": "No video provided; baseline minimum green allocated.",
            }

    if provided_approaches:
        workers = min(4, len(provided_approaches))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_dir = {
                executor.submit(
                    analyse_directional_video_clip,
                    path,
                    d,
                    output_dir,
                    sample_fps,
                    cancellation_check,
                ): d
                for d, path in provided_approaches.items()
            }
            for future in as_completed(future_to_dir):
                d = future_to_dir[future]
                res = future.result()
                directional_results[d] = res
                directional_demands[d] = res["effective_demand"]
                directional_metrics[d] = res["metrics"]
                combined_detections.extend(res["detections"])
                total_unique_all_directions += res["metrics"]["unique_vehicles"]
                annotated_files[d] = res["annotated_filename"]

    # Primary representative annotated filename (North, or first provided direction)
    primary_annotated = None
    for d in DIRECTIONS:
        if d in annotated_files:
            primary_annotated = annotated_files[d]
            break

    note = (
        f"Multi-video temporal analysis across {len(annotated_files)} provided approaches. "
        f"Tracked {total_unique_all_directions} total vehicles with queue depth and flow rate weighting."
    )

    return {
        "counts": directional_demands,
        "total_count": total_unique_all_directions,
        "detections": combined_detections,
        "directional_metrics": directional_metrics,
        "annotated_filename": primary_annotated or "no-video-annotated.jpg",
        "annotated_files": annotated_files,
        "analysis_note": note,
        "analysis_provider": "local-yolo-multi-video-tracker",
    }
