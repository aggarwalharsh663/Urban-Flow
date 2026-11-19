# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
import torch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from services import detection, video_tracker
from services.detection import (
    ThreadSafeYOLO,
    _get_model,
    compute_optimal_pytorch_threads,
    configure_pytorch_threads,
    get_detection_status,
    get_pytorch_thread_config,
    reset_pytorch_thread_config_state_for_testing,
)
from services.video_tracker import (
    analyse_directional_video_clip,
    analyse_multi_directional_videos,
)


class FakeBox:
    def __init__(self, cls_id: int, conf: float, xyxy: list[int]):
        self.cls = torch.tensor([cls_id], dtype=torch.float32)
        self.conf = torch.tensor([conf], dtype=torch.float32)
        self.xyxy = torch.tensor([xyxy], dtype=torch.float32)


class FakeResult:
    def __init__(self, boxes=None):
        self.boxes = boxes or [FakeBox(2, 0.88, [100, 100, 200, 200])]
        self.names = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


class MockYOLOModel:
    def __init__(self):
        self.names = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

    def predict(self, source, **kwargs):
        is_batch = isinstance(source, list)
        count = len(source) if is_batch else 1
        return [FakeResult() for _ in range(count)]


def create_synthetic_mp4(filepath: Path, num_frames: int = 25, width: int = 640, height: int = 480, fps: float = 10.0):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(filepath), fourcc, fps, (width, height))
    for i in range(num_frames):
        img = np.zeros((height, width, 3), dtype=np.uint8)
        cx = int((i / num_frames) * (width - 100)) + 50
        cy = int((i / num_frames) * (height - 100)) + 50
        cv2.rectangle(img, (cx, cy), (cx + 50, cy + 40), (200, 200, 200), -1)
        out.write(img)
    out.release()


@pytest.fixture(autouse=True)
def clean_config_state():
    reset_pytorch_thread_config_state_for_testing()
    yield
    reset_pytorch_thread_config_state_for_testing()


def test_thread_configuration_happens_centrally():
    """Requirement 1: Verify thread configuration happens centrally and follows hardware-adaptive rules."""
    # Test topology computation
    assert compute_optimal_pytorch_threads(cpu_cores=2) == (1, 1)
    assert compute_optimal_pytorch_threads(cpu_cores=4) == (2, 1)
    assert compute_optimal_pytorch_threads(cpu_cores=8) == (4, 2)
    assert compute_optimal_pytorch_threads(cpu_cores=16) == (8, 4)
    assert compute_optimal_pytorch_threads(cpu_cores=32) == (8, 4)

    # Test environment variable override
    with patch.dict(os.environ, {"URBANFLOW_TORCH_THREADS": "3", "URBANFLOW_TORCH_INTEROP_THREADS": "2"}):
        assert compute_optimal_pytorch_threads(cpu_cores=8) == (3, 2)

    # Test central configuration call
    cfg = configure_pytorch_threads(num_threads=2, num_interop_threads=1, force=True)
    assert cfg["intra_op"] == 2
    assert torch.get_num_threads() == 2


def test_worker_functions_do_not_mutate_global_pytorch_thread_settings(tmp_path):
    """Requirement 2: Verify worker functions do not mutate global PyTorch thread settings."""
    video_path = tmp_path / "north_test.mp4"
    create_synthetic_mp4(video_path, num_frames=25)

    configure_pytorch_threads(num_threads=2, force=True)
    baseline_threads = torch.get_num_threads()

    mock_model = MockYOLOModel()
    thread_safe_model = ThreadSafeYOLO(mock_model)

    # Spy on torch.set_num_threads
    original_set_num_threads = torch.set_num_threads
    set_num_threads_calls = []

    def tracking_set_num_threads(n):
        set_num_threads_calls.append(n)
        return original_set_num_threads(n)

    with patch.object(detection, "_get_model", return_value=thread_safe_model):
        with patch.object(video_tracker, "_get_model", return_value=thread_safe_model):
            with patch("torch.set_num_threads", side_effect=tracking_set_num_threads):
                result = analyse_directional_video_clip(
                    video_path=video_path,
                    direction="North",
                    output_dir=tmp_path,
                    sample_fps=1.0,
                )

    # Worker function must NOT call torch.set_num_threads
    assert len(set_num_threads_calls) == 0, f"Expected 0 calls to torch.set_num_threads in worker, got {len(set_num_threads_calls)}"
    assert torch.get_num_threads() == baseline_threads
    assert result["direction"] == "North"


def test_multiple_video_workers_use_stable_configuration(tmp_path):
    """Requirement 3: Verify multiple concurrent video workers execute with stable thread configuration."""
    videos = {}
    for d in ("North", "South", "East", "West"):
        vp = tmp_path / f"{d.lower()}_test.mp4"
        create_synthetic_mp4(vp, num_frames=25)
        videos[d] = vp

    configure_pytorch_threads(num_threads=2, force=True)
    initial_threads = torch.get_num_threads()

    mock_model = MockYOLOModel()
    thread_safe_model = ThreadSafeYOLO(mock_model)

    observed_threads = []

    def wrapped_clip_worker(path, direction):
        observed_threads.append(torch.get_num_threads())
        res = analyse_directional_video_clip(path, direction, tmp_path, sample_fps=1.0)
        observed_threads.append(torch.get_num_threads())
        return res

    with patch.object(detection, "_get_model", return_value=thread_safe_model):
        with patch.object(video_tracker, "_get_model", return_value=thread_safe_model):
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(wrapped_clip_worker, p, d) for d, p in videos.items()]
                results = [f.result() for f in futures]

    assert len(results) == 4
    # All threads observed must match initial configured threads exactly
    for t in observed_threads:
        assert t == initial_threads, f"Expected stable thread count {initial_threads}, got {t}"


def test_photo_inference_works(tmp_path):
    """Requirement 4: Verify single-photo inference operates correctly with centralized thread configuration."""
    img_path = tmp_path / "test_photo.jpg"
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.imwrite(str(img_path), img)

    configure_pytorch_threads(num_threads=2, force=True)

    mock_model = MockYOLOModel()
    thread_safe_model = ThreadSafeYOLO(mock_model)

    with patch.object(detection, "_get_model", return_value=thread_safe_model):
        result = detection.analyse_image(img_path, output_dir=tmp_path)

    assert "counts" in result
    assert "total_count" in result
    assert "annotated_filename" in result
    assert torch.get_num_threads() == 2


def test_four_direction_inference_works(tmp_path):
    """Requirement 5: Verify four-direction video analysis completes and preserves thread configuration."""
    videos = {}
    for d in ("North", "South", "East", "West"):
        vp = tmp_path / f"{d.lower()}_test.mp4"
        create_synthetic_mp4(vp, num_frames=25)
        videos[d] = str(vp)

    configure_pytorch_threads(num_threads=2, force=True)

    mock_model = MockYOLOModel()
    thread_safe_model = ThreadSafeYOLO(mock_model)

    with patch.object(detection, "_get_model", return_value=thread_safe_model):
        with patch.object(video_tracker, "_get_model", return_value=thread_safe_model):
            result = analyse_multi_directional_videos(videos, output_dir=tmp_path, sample_fps=1.0)

    assert "counts" in result
    assert "directional_metrics" in result
    assert set(result["counts"].keys()) == {"North", "South", "East", "West"}
    assert torch.get_num_threads() == 2


def test_repeated_jobs_do_not_change_thread_configuration():
    """Requirement 6: Verify repeated configuration calls and jobs do not re-invoke set_num_threads."""
    configure_pytorch_threads(num_threads=2, force=True)

    with patch("torch.set_num_threads") as mock_set_intra:
        # Subsequent calls without force=True must be idempotent no-ops
        res1 = configure_pytorch_threads()
        res2 = configure_pytorch_threads()
        assert res1["intra_op"] == 2
        assert res2["intra_op"] == 2
        mock_set_intra.assert_not_called()


def test_startup_works_when_pytorch_already_initialized():
    """Requirement 7: Verify startup handles PyTorch already having started parallel work without crashing."""
    reset_pytorch_thread_config_state_for_testing()

    with patch("torch.set_num_interop_threads", side_effect=RuntimeError("cannot set number of interop threads after parallel work has started")):
        # Must not raise RuntimeError
        cfg = configure_pytorch_threads(num_threads=2, force=True)
        assert cfg["intra_op"] == 2


def test_exceptions_during_initialization_are_handled_safely():
    """Requirement 8: Verify arbitrary exceptions during thread initialization are handled safely."""
    reset_pytorch_thread_config_state_for_testing()

    with patch("torch.set_num_threads", side_effect=RuntimeError("simulated low-level thread pool failure")):
        # Must not crash
        cfg = configure_pytorch_threads(num_threads=2, force=True)
        assert "intra_op" in cfg


def test_get_detection_status_includes_pytorch_threads():
    """Verify get_detection_status returns thread configuration details."""
    configure_pytorch_threads(num_threads=2, force=True)
    status = get_detection_status()
    assert "pytorch_threads" in status
    assert status["pytorch_threads"]["intra_op"] == 2
