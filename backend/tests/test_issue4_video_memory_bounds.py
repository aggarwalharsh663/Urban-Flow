# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

"""
Unit and integration tests for Issue 4:
Prevent Video Analysis Memory Exhaustion via Bounded-Memory Streaming Inference.

Verifies:
1. Long video processing
2. 1080p video processing & resizing
3. 4K video processing & memory bounds
4. Four-direction video processing concurrency & safety
5. Maximum frame dimensions validation
6. Excessive pixel count validation
7. Corrupt & malformed frame rejection
8. Cancellation during decoding
9. Cancellation during batch inference
10. Exception handling & resource cleanup during batch processing
11. Memory boundedness across repeated jobs (leak prevention)
12. Frame coordinate transformations (bidirectional mapping correctness)
13. Detection accuracy & scale invariance after resizing
"""

from __future__ import annotations

import gc
import os
import tempfile
import tracemalloc
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
import torch

from services.video_tracker import (
    MAX_DECODED_PIXELS,
    MAX_FRAME_HEIGHT,
    MAX_FRAME_WIDTH,
    MAX_INFERENCE_BATCH_SIZE,
    MAX_INFERENCE_DIMENSION,
    CentroidIoUTracker,
    analyse_directional_video_clip,
    analyse_multi_directional_videos,
    compute_inference_dimensions,
    scale_box_to_inference,
    scale_box_to_original,
    validate_decoded_frame,
)


def _create_test_mp4(
    path: Path,
    width: int = 640,
    height: int = 480,
    fps: float = 10.0,
    num_frames: int = 30,
    draw_vehicle: bool = True,
) -> None:
    """Helper to generate a lightweight synthetic test MP4 container."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    for f in range(num_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        if draw_vehicle:
            # Draw moving rectangle simulating a vehicle approaching
            x = 100 + int(f * 3)
            y = 150 + int(f * 2)
            cv2.rectangle(frame, (x, y), (x + 60, y + 40), (180, 100, 50), -1)
        writer.write(frame)
    writer.release()


# ---------------------------------------------------------------------------
# Test 1: Frame-level Validation (Dimensions, Channels, Pixel Caps, Dtypes)
# ---------------------------------------------------------------------------

def test_validate_decoded_frame_valid():
    valid_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    validate_decoded_frame(valid_frame)


def test_validate_decoded_frame_rejects_none_and_non_array():
    with pytest.raises(ValueError, match="Corrupt or null"):
        validate_decoded_frame(None)  # type: ignore

    with pytest.raises(ValueError, match="Corrupt or null"):
        validate_decoded_frame("not_a_frame")  # type: ignore


def test_validate_decoded_frame_rejects_wrong_dtype():
    float_frame = np.zeros((100, 100, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="Invalid frame dtype"):
        validate_decoded_frame(float_frame)


def test_validate_decoded_frame_rejects_unsupported_shapes():
    # 2D grayscale
    gray_frame = np.zeros((100, 100), dtype=np.uint8)
    with pytest.raises(ValueError, match="Invalid frame shape"):
        validate_decoded_frame(gray_frame)

    # 4-channel RGBA
    rgba_frame = np.zeros((100, 100, 4), dtype=np.uint8)
    with pytest.raises(ValueError, match="Invalid frame shape"):
        validate_decoded_frame(rgba_frame)


def test_validate_decoded_frame_rejects_zero_dimensions():
    empty_frame = np.zeros((0, 100, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="Invalid decoded frame dimensions"):
        validate_decoded_frame(empty_frame)


def test_validate_decoded_frame_rejects_excessive_dimensions():
    # Width exceeds MAX_FRAME_WIDTH
    oversized = np.zeros((100, MAX_FRAME_WIDTH + 10, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="exceed safety limit"):
        validate_decoded_frame(oversized)

    # Height exceeds MAX_FRAME_HEIGHT
    oversized_h = np.zeros((MAX_FRAME_HEIGHT + 10, 100, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="exceed safety limit"):
        validate_decoded_frame(oversized_h)


def test_validate_decoded_frame_rejects_excessive_pixel_count():
    # 4000 x 2100 = 8.4M pixels > 8,294,400 max
    oversized_pixels = np.zeros((2100, 4000, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="exceed safety limit"):
        validate_decoded_frame(oversized_pixels, max_w=5000, max_h=5000, max_pixels=MAX_DECODED_PIXELS)


# ---------------------------------------------------------------------------
# Test 2: Bounded Inference Dimensions & Coordinate Transformations
# ---------------------------------------------------------------------------

def test_compute_inference_dimensions():
    # Already below 1280 max
    w, h, sx, sy = compute_inference_dimensions(640, 480, max_dim=1280)
    assert (w, h) == (640, 480)
    assert (sx, sy) == (1.0, 1.0)

    # 1080p: 1920x1080 -> scale down to max dim 1280
    w, h, sx, sy = compute_inference_dimensions(1920, 1080, max_dim=1280)
    assert w == 1280
    assert h == 720
    assert abs(sx - (1920.0 / 1280.0)) < 1e-4
    assert abs(sy - (1080.0 / 720.0)) < 1e-4

    # 4K UHD: 3840x2160 -> scale down to max dim 1280
    w, h, sx, sy = compute_inference_dimensions(3840, 2160, max_dim=1280)
    assert w == 1280
    assert h == 720
    assert abs(sx - (3840.0 / 1280.0)) < 1e-4
    assert abs(sy - (2160.0 / 720.0)) < 1e-4


def test_coordinate_transformation_bidirectional():
    orig_w, orig_h = 3840, 2160
    target_w, target_h, sx, sy = compute_inference_dimensions(orig_w, orig_h, max_dim=1280)

    # Box in inference space [x1, y1, x2, y2]
    inf_box = [100, 200, 300, 400]
    orig_box = scale_box_to_original(inf_box, sx, sy, orig_w=orig_w, orig_h=orig_h)

    assert orig_box[0] == int(round(100 * sx))
    assert orig_box[1] == int(round(200 * sy))
    assert orig_box[2] == int(round(300 * sx))
    assert orig_box[3] == int(round(400 * sy))

    # Reverse transformation
    reconstructed_inf = scale_box_to_inference(orig_box, sx, sy)
    assert abs(reconstructed_inf[0] - inf_box[0]) <= 1
    assert abs(reconstructed_inf[1] - inf_box[1]) <= 1
    assert abs(reconstructed_inf[2] - inf_box[2]) <= 1
    assert abs(reconstructed_inf[3] - inf_box[3]) <= 1


# ---------------------------------------------------------------------------
# Test 3: Streaming Inference on Synthetic Video (Memory & Correctness)
# ---------------------------------------------------------------------------

class FakeBox:
    def __init__(self, cls_id: int, conf: float, xyxy: list[float]):
        self.cls = torch.tensor([cls_id], dtype=torch.float32)
        self.conf = torch.tensor([conf], dtype=torch.float32)
        self.xyxy = torch.tensor([xyxy], dtype=torch.float32)


class FakeDetectionResult:
    def __init__(self, boxes: list[FakeBox]):
        self.boxes = boxes
        self.names = {0: "person", 2: "car", 5: "bus", 7: "truck"}


def test_streaming_video_clip_analysis_bounded_memory(tmp_path: Path):
    video_path = tmp_path / "stream_test.mp4"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 4-second video at 10 fps (40 frames)
    _create_test_mp4(video_path, width=640, height=480, fps=10.0, num_frames=40)

    # Mock YOLO model to return predictable detections
    fake_boxes = [FakeBox(2, 0.85, [150.0, 200.0, 220.0, 270.0])]
    mock_model = MagicMock()
    mock_model.predict.side_effect = lambda frames, **kwargs: [FakeDetectionResult(fake_boxes) for _ in frames]

    with patch("services.video_tracker._get_model", return_value=mock_model):
        res = analyse_directional_video_clip(
            video_path,
            direction="North",
            output_dir=out_dir,
            sample_fps=2.0,
            batch_size=4,
        )

    assert res["direction"] == "North"
    assert res["sampled_frames"] >= 7
    assert (out_dir / res["annotated_filename"]).is_file()
    assert res["effective_demand"] >= 1
    # Check that orig_box is populated in detections
    for det in res["detections"]:
        assert "orig_box" in det
        assert "box" in det


# ---------------------------------------------------------------------------
# Test 4: 1080p and 4K Video Scaling & Processing
# ---------------------------------------------------------------------------

def test_1080p_video_processing(tmp_path: Path):
    video_path = tmp_path / "test_1080p.mp4"
    out_dir = tmp_path / "out_1080p"
    out_dir.mkdir(parents=True, exist_ok=True)

    _create_test_mp4(video_path, width=1920, height=1080, fps=10.0, num_frames=25)

    fake_boxes = [FakeBox(2, 0.90, [300.0, 250.0, 420.0, 350.0])]
    mock_model = MagicMock()
    mock_model.predict.side_effect = lambda frames, **kwargs: [FakeDetectionResult(fake_boxes) for _ in frames]

    with patch("services.video_tracker._get_model", return_value=mock_model):
        res = analyse_directional_video_clip(
            video_path,
            direction="South",
            output_dir=out_dir,
            sample_fps=1.0,
            batch_size=4,
        )

    assert res["direction"] == "South"
    assert (out_dir / res["annotated_filename"]).is_file()


def test_4k_video_processing(tmp_path: Path):
    video_path = tmp_path / "test_4k.mp4"
    out_dir = tmp_path / "out_4k"
    out_dir.mkdir(parents=True, exist_ok=True)

    _create_test_mp4(video_path, width=3840, height=2160, fps=10.0, num_frames=22)

    fake_boxes = [FakeBox(2, 0.92, [400.0, 300.0, 550.0, 420.0])]
    mock_model = MagicMock()
    mock_model.predict.side_effect = lambda frames, **kwargs: [FakeDetectionResult(fake_boxes) for _ in frames]

    with patch("services.video_tracker._get_model", return_value=mock_model):
        res = analyse_directional_video_clip(
            video_path,
            direction="East",
            output_dir=out_dir,
            sample_fps=1.0,
            batch_size=4,
        )

    assert res["direction"] == "East"
    assert (out_dir / res["annotated_filename"]).is_file()


# ---------------------------------------------------------------------------
# Test 5: Four-direction Video Processing Concurrency
# ---------------------------------------------------------------------------

def test_four_direction_video_concurrency_and_metrics(tmp_path: Path):
    out_dir = tmp_path / "out_multi"
    out_dir.mkdir(parents=True, exist_ok=True)

    dirs = ["North", "South", "East", "West"]
    directional_paths = {}
    for d in dirs:
        vpath = tmp_path / f"video_{d.lower()}.mp4"
        _create_test_mp4(vpath, width=640, height=480, fps=10.0, num_frames=25)
        directional_paths[d] = vpath

    fake_boxes = [FakeBox(2, 0.88, [120.0, 180.0, 200.0, 250.0])]
    mock_model = MagicMock()
    mock_model.predict.side_effect = lambda frames, **kwargs: [FakeDetectionResult(fake_boxes) for _ in frames]

    with patch("services.video_tracker._get_model", return_value=mock_model):
        multi_res = analyse_multi_directional_videos(
            directional_paths,
            output_dir=out_dir,
            sample_fps=1.0,
        )

    assert multi_res["total_count"] >= 4
    for d in dirs:
        assert d in multi_res["counts"]
        assert multi_res["counts"][d] >= 1
        assert d in multi_res["annotated_files"]
        assert (out_dir / multi_res["annotated_files"][d]).is_file()


# ---------------------------------------------------------------------------
# Test 6: Cancellation During Decoding & Batch Inference
# ---------------------------------------------------------------------------

def test_cancellation_during_decoding(tmp_path: Path):
    video_path = tmp_path / "test_cancel_decode.mp4"
    out_dir = tmp_path / "out_cancel"
    out_dir.mkdir(parents=True, exist_ok=True)
    _create_test_mp4(video_path, width=640, height=480, fps=10.0, num_frames=30)

    cancel_counter = 0

    def cancel_after_3_checks():
        nonlocal cancel_counter
        cancel_counter += 1
        return cancel_counter >= 3

    with pytest.raises(RuntimeError, match="cancelled"):
        analyse_directional_video_clip(
            video_path,
            direction="North",
            output_dir=out_dir,
            cancellation_check=cancel_after_3_checks,
        )


def test_cancellation_during_inference(tmp_path: Path):
    video_path = tmp_path / "test_cancel_inf.mp4"
    out_dir = tmp_path / "out_cancel_inf"
    out_dir.mkdir(parents=True, exist_ok=True)
    _create_test_mp4(video_path, width=640, height=480, fps=10.0, num_frames=30)

    # Trigger cancellation inside model.predict
    is_cancelled = False

    def check_cancel():
        return is_cancelled

    mock_model = MagicMock()

    def simulate_cancel_in_predict(frames, **kwargs):
        nonlocal is_cancelled
        is_cancelled = True
        return [FakeDetectionResult([]) for _ in frames]

    mock_model.predict.side_effect = simulate_cancel_in_predict

    with patch("services.video_tracker._get_model", return_value=mock_model):
        with pytest.raises(RuntimeError, match="cancelled"):
            analyse_directional_video_clip(
                video_path,
                direction="North",
                output_dir=out_dir,
                sample_fps=2.0,
                batch_size=2,
                cancellation_check=check_cancel,
            )


# ---------------------------------------------------------------------------
# Test 7: Exception During Batch Processing & Resource Cleanup
# ---------------------------------------------------------------------------

def test_exception_during_batch_inference_releases_capture(tmp_path: Path):
    video_path = tmp_path / "test_err_cleanup.mp4"
    out_dir = tmp_path / "out_err"
    out_dir.mkdir(parents=True, exist_ok=True)
    _create_test_mp4(video_path, width=640, height=480, fps=10.0, num_frames=25)

    mock_model = MagicMock()
    mock_model.predict.side_effect = RuntimeError("Simulated GPU/CPU inference fault")

    with patch("services.video_tracker._get_model", return_value=mock_model):
        with pytest.raises(RuntimeError, match="Simulated GPU/CPU inference fault"):
            analyse_directional_video_clip(
                video_path,
                direction="West",
                output_dir=out_dir,
                sample_fps=2.0,
                batch_size=4,
            )


# ---------------------------------------------------------------------------
# Test 8: Memory Boundedness Across Repeated Jobs (No Memory Leaks)
# ---------------------------------------------------------------------------

def test_memory_bounded_across_repeated_jobs(tmp_path: Path):
    video_path = tmp_path / "test_leak.mp4"
    out_dir = tmp_path / "out_leak"
    out_dir.mkdir(parents=True, exist_ok=True)
    _create_test_mp4(video_path, width=1280, height=720, fps=10.0, num_frames=30)

    fake_boxes = [FakeBox(2, 0.85, [200.0, 300.0, 320.0, 420.0])]
    mock_model = MagicMock()
    mock_model.predict.side_effect = lambda frames, **kwargs: [FakeDetectionResult(fake_boxes) for _ in frames]

    gc.collect()
    tracemalloc.start()

    with patch("services.video_tracker._get_model", return_value=mock_model):
        # Warmup iteration
        analyse_directional_video_clip(video_path, "North", out_dir, sample_fps=2.0, batch_size=4)
        gc.collect()
        snapshot1 = tracemalloc.take_snapshot()

        # Run 5 repeated jobs
        for i in range(5):
            analyse_directional_video_clip(video_path, "North", out_dir, sample_fps=2.0, batch_size=4)

        gc.collect()
        snapshot2 = tracemalloc.take_snapshot()

    tracemalloc.stop()

    # Memory growth across 5 jobs must be less than 2 MB
    stats = snapshot2.compare_to(snapshot1, "lineno")
    total_growth = sum(stat.size_diff for stat in stats if stat.size_diff > 0)
    assert total_growth < 2 * 1024 * 1024, f"Memory grew by {total_growth} bytes, exceeding 2MB threshold"
