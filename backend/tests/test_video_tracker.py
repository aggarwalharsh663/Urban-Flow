"""
Unit and integration tests for UrbanFlow video tracking engine,
safety validations, and multi-directional video analysis pipeline.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from services.planning import DIRECTIONS, calculate_green_times, create_signal_plan
from services.video_tracker import (
    CentroidIoUTracker,
    VehicleTrack,
    analyse_multi_directional_videos,
    compute_iou,
    validate_directional_video,
)


def test_compute_iou_exact_and_disjoint():
    box1 = [10, 10, 50, 50]
    box2 = [10, 10, 50, 50]
    assert compute_iou(box1, box2) == 1.0

    box_disjoint = [60, 60, 100, 100]
    assert compute_iou(box1, box_disjoint) == 0.0

    # Half overlap: box1 is 40x40 (area 1600), box_half is [10, 10, 30, 50] (area 800)
    box_half = [10, 10, 30, 50]
    # intersection: 20 * 40 = 800, union: 1600 + 800 - 800 = 1600, iou = 0.5
    assert compute_iou(box1, box_half) == 0.5


def test_tracker_registration_and_association():
    tracker = CentroidIoUTracker(max_disappeared=3, min_displacement=20.0)

    # Frame 1: Two vehicles detected
    frame_shape = (720, 1280, 3)
    dets_f1 = [
        {"box": [100, 200, 180, 280], "class": "car", "confidence": 0.85},
        {"box": [300, 200, 380, 280], "class": "truck", "confidence": 0.90},
    ]
    tracks = tracker.update(dets_f1, timestamp_sec=0.0, frame_shape=frame_shape)
    assert len(tracks) == 2
    assert tracks[0].track_id == 1
    assert tracks[1].track_id == 2
    assert tracker.frame_peak_queue == 2

    # Frame 2: Vehicle 1 moved forward, Vehicle 2 remained stationary
    dets_f2 = [
        {"box": [100, 240, 180, 320], "class": "car", "confidence": 0.88},  # dy = +40px
        {"box": [300, 200, 380, 280], "class": "truck", "confidence": 0.92},  # stationary
    ]
    tracks_f2 = tracker.update(dets_f2, timestamp_sec=0.5, frame_shape=frame_shape)
    assert len(tracks_f2) == 2
    tr_car = next(t for t in tracks_f2 if t.label == "car")
    tr_truck = next(t for t in tracks_f2 if t.label == "truck")

    assert tr_car.total_displacement >= 30.0
    assert tr_car.is_stationary is False
    assert tr_truck.is_stationary is True


def test_tracker_demand_formula():
    tracker = CentroidIoUTracker()
    frame_shape = (720, 1280, 3)

    # Simulate 5 vehicles detected over 30 seconds
    for sec in range(5):
        dets = [
            {"box": [100 * (i + 1), 200, 100 * (i + 1) + 60, 280], "class": "car", "confidence": 0.8}
            for i in range(sec + 1)
        ]
        tracker.update(dets, timestamp_sec=float(sec), frame_shape=frame_shape)

    summary = tracker.get_summary(video_duration_sec=30.0)
    assert summary["unique_vehicles"] >= 5
    assert summary["duration_seconds"] == 30.0
    assert summary["peak_queue"] >= 1
    # Effective demand must be a positive integer bounded by MAX_VEHICLE_COUNT
    assert isinstance(summary["effective_demand"], int)
    assert summary["effective_demand"] > 0


def test_cross_traffic_and_opposing_corridor_filtering():
    tracker = CentroidIoUTracker()
    frame_shape = (720, 1280, 3)

    # Frame 1:
    # 1. Approach queue vehicle: at x=700, y=500 (waiting at red light)
    # 2. Opposing lane vehicle: at x=200, y=300 (other side of road)
    # 3. Cross-traffic vehicle: at x=400, y=200 (horizontal crossing)
    f1_dets = [
        {"box": [680, 480, 740, 540], "class": "car", "confidence": 0.9},
        {"box": [180, 280, 240, 340], "class": "truck", "confidence": 0.85},
        {"box": [380, 180, 440, 240], "class": "car", "confidence": 0.88},
    ]
    tracker.update(f1_dets, timestamp_sec=0.0, frame_shape=frame_shape)

    # Frame 2 (0.5s later):
    # Approach vehicle remains stationary in queue (x=700, y=500)
    # Opposing vehicle moves upward/away (dy = -50) on other side: y=250
    # Cross vehicle moves horizontally (dx = +120, dy = +5): x=520
    f2_dets = [
        {"box": [680, 480, 740, 540], "class": "car", "confidence": 0.9},
        {"box": [180, 230, 240, 290], "class": "truck", "confidence": 0.85},
        {"box": [500, 185, 560, 245], "class": "car", "confidence": 0.88},
    ]
    tracker.update(f2_dets, timestamp_sec=0.5, frame_shape=frame_shape)

    # Frame 3 (1.0s later):
    # Approach vehicle discharges forward through green light: dy = +60 (y=560)
    # Opposing vehicle continues moving away: dy = -100 (y=200)
    # Cross vehicle continues moving horizontally: dx = +240 (x=640)
    f3_dets = [
        {"box": [685, 540, 745, 600], "class": "car", "confidence": 0.9},
        {"box": [180, 180, 240, 240], "class": "truck", "confidence": 0.85},
        {"box": [620, 190, 680, 250], "class": "car", "confidence": 0.88},
    ]
    tracker.update(f3_dets, timestamp_sec=1.0, frame_shape=frame_shape)

    summary = tracker.get_summary(video_duration_sec=10.0)
    # Cross traffic and opposing traffic must be filtered, retaining only monitored approach
    assert summary["cross_traffic_filtered"] >= 1
    assert summary["opposing_traffic_filtered"] >= 1
    assert summary["unique_vehicles"] == 1


def test_distant_background_exclusion():
    tracker = CentroidIoUTracker()
    frame_shape = (720, 1280, 3)
    # Distant vehicle in upper background across junction (y = 120 < 0.32 * 720)
    dets = [
        {"box": [500, 100, 560, 140], "class": "car", "confidence": 0.85},
    ]
    tracker.update(dets, timestamp_sec=0.0, frame_shape=frame_shape)
    summary = tracker.get_summary(video_duration_sec=10.0)
    # Distant background outside approach corridor must be excluded from approach demand
    assert summary["opposing_traffic_filtered"] >= 1


def test_validate_directional_video_safety(tmp_path: Path):
    # Empty file
    empty_file = tmp_path / "empty.mp4"
    empty_file.write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        validate_directional_video(empty_file)

    # Invalid magic bytes
    fake_file = tmp_path / "fake.mp4"
    fake_file.write_bytes(b"NOT_A_REAL_MP4_HEADER_HERE_PADDING_DATA")
    with pytest.raises(ValueError, match="magic signature"):
        validate_directional_video(fake_file)

    # Non-existent file
    missing = tmp_path / "missing.mp4"
    with pytest.raises(ValueError, match="does not exist"):
        validate_directional_video(missing)


def _create_synthetic_mp4(path: Path, width=640, height=480, fps=10.0, num_frames=30):
    """Generates a small valid MP4 test video with synthetic frames."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    for f in range(num_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Draw moving rectangle simulating a vehicle
        x = 50 + f * 5
        cv2.rectangle(frame, (x, 100), (x + 80, 180), (200, 100, 50), -1)
        writer.write(frame)
    writer.release()


def test_synthetic_video_pipeline_and_graceful_fallback(tmp_path: Path):
    video_dir = tmp_path / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)
    north_video = video_dir / "north.mp4"
    east_video = video_dir / "east.mp4"

    # Create 3-second synthetic videos at 10 fps (30 frames)
    _create_synthetic_mp4(north_video, fps=10.0, num_frames=30)
    _create_synthetic_mp4(east_video, fps=10.0, num_frames=30)

    # Partial 2-video input (North and East provided; South and West missing)
    directional_inputs = {
        "North": north_video,
        "East": east_video,
        "South": None,
        "West": None,
    }

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = analyse_multi_directional_videos(
        directional_inputs,
        out_dir,
        sample_fps=2.0,
    )

    assert "counts" in result
    assert set(result["counts"].keys()) == set(DIRECTIONS)
    # Missing approaches should have 0 demand
    assert result["counts"]["South"] == 0
    assert result["counts"]["West"] == 0
    assert "directional_metrics" in result
    assert result["directional_metrics"]["South"]["effective_demand"] == 0

    # Ensure result integrates seamlessly into deterministic signal plan
    plan = create_signal_plan(
        result["counts"],
        junction_name="Test Video Junction",
        source="multi_video",
    )
    assert plan["source"] == "multi_video"
    assert sum(plan["green_times"].values()) == 120
    # Every direction receives at least the minimum green floor
    for d in DIRECTIONS:
        assert plan["green_times"][d] >= 10
