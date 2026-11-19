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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest
import torch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from services import detection, video_tracker
from services.detection import (
    ModelUnavailableError,
    ThreadSafeYOLO,
    _get_model,
    get_inference_lock,
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
        self.boxes = boxes or [FakeBox(2, 0.88, [60, 80, 160, 180])]
        self.names = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


class ConcurrentDetectionDetectorModel:
    """
    Simulated YOLO model that tracks concurrent entries into predict().
    If more than one thread enters predict() concurrently, race_detected is set to True.
    """

    def __init__(self, simulated_latency: float = 0.02, custom_boxes_fn=None):
        self.active_threads = 0
        self.max_concurrency = 0
        self.race_detected = False
        self.call_count = 0
        self.simulated_latency = simulated_latency
        self.custom_boxes_fn = custom_boxes_fn
        self._internal_lock = threading.Lock()
        self.names = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

    def predict(self, source, **kwargs):
        with self._internal_lock:
            self.active_threads += 1
            if self.active_threads > self.max_concurrency:
                self.max_concurrency = self.active_threads
            if self.active_threads > 1:
                self.race_detected = True

        try:
            # Simulate forward pass processing time
            time.sleep(self.simulated_latency)
            is_batch = isinstance(source, list)
            count = len(source) if is_batch else 1
            if self.custom_boxes_fn:
                return [FakeResult(self.custom_boxes_fn()) for _ in range(count)]
            return [FakeResult() for _ in range(count)]
        finally:
            with self._internal_lock:
                self.active_threads -= 1
                self.call_count += 1


def _create_synthetic_mp4(path: Path, width: int = 320, height: int = 240, fps: float = 10.0, num_frames: int = 25) -> Path:
    """Create a minimal valid synthetic MP4 file with moving rectangular pattern."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    for f in range(num_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        x = 20 + f * 5
        cv2.rectangle(frame, (x, 50), (x + 40, 100), (0, 255, 0), -1)
        writer.write(frame)
    writer.release()
    return path


# 1. Concurrent calls to the shared model
def test_concurrent_calls_to_shared_model(monkeypatch: pytest.MonkeyPatch):
    raw_detector = ConcurrentDetectionDetectorModel(simulated_latency=0.03)
    shared_lock = threading.RLock()
    safe_model = ThreadSafeYOLO(raw_detector, shared_lock)
    monkeypatch.setattr(detection, "_model", safe_model)

    dummy_frame = np.zeros((640, 640, 3), dtype=np.uint8)
    num_threads = 8
    results = [None] * num_threads

    def worker(idx: int):
        # Call predict on the shared thread-safe model
        res = safe_model.predict([dummy_frame] * 2, verbose=False)
        results[idx] = res

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Assert all threads completed with non-null results
    assert all(r is not None for r in results)
    # Peak concurrency inside predict() must strictly equal 1
    assert raw_detector.max_concurrency == 1
    assert not raw_detector.race_detected
    assert raw_detector.call_count == num_threads


# 2. Four-direction video analysis with synchronization
def test_four_direction_video_analysis_synchronization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    raw_detector = ConcurrentDetectionDetectorModel(simulated_latency=0.015)
    safe_model = ThreadSafeYOLO(raw_detector, get_inference_lock())
    monkeypatch.setattr(detection, "_model", safe_model)

    video_dir = tmp_path / "directional_cams"
    paths = {
        "North": _create_synthetic_mp4(video_dir / "north.mp4"),
        "South": _create_synthetic_mp4(video_dir / "south.mp4"),
        "East": _create_synthetic_mp4(video_dir / "east.mp4"),
        "West": _create_synthetic_mp4(video_dir / "west.mp4"),
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = analyse_multi_directional_videos(paths, out_dir, sample_fps=2.0)

    # Verification of multi-video tracking results
    assert "counts" in result
    assert set(result["counts"].keys()) == {"North", "South", "East", "West"}
    assert result["total_count"] >= 0
    assert len(result["annotated_files"]) == 4

    # Synchronization verification
    assert raw_detector.max_concurrency == 1, "Predictor must never be entered by >1 thread simultaneously"
    assert not raw_detector.race_detected, "No race condition allowed across directional workers"


# 3. Cross-direction result isolation
def test_cross_direction_result_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Setup custom detection responses varying by thread or box count
    call_counter = 0
    counter_lock = threading.Lock()

    def variable_boxes():
        nonlocal call_counter
        with counter_lock:
            call_counter += 1
            idx = call_counter
        # Alternate box coordinates and classes
        return [FakeBox(2, 0.90, [10 * idx, 20 * idx, 50 * idx, 60 * idx])]

    raw_detector = ConcurrentDetectionDetectorModel(simulated_latency=0.01, custom_boxes_fn=variable_boxes)
    safe_model = ThreadSafeYOLO(raw_detector, get_inference_lock())
    monkeypatch.setattr(detection, "_model", safe_model)

    video_dir = tmp_path / "cams"
    paths = {
        "North": _create_synthetic_mp4(video_dir / "north.mp4"),
        "South": _create_synthetic_mp4(video_dir / "south.mp4"),
    }
    out_dir = tmp_path / "out"

    result = analyse_multi_directional_videos(paths, out_dir, sample_fps=2.0)

    metrics = result["directional_metrics"]
    assert "North" in metrics and "South" in metrics
    # Results must be properly isolated
    assert "unique_vehicles" in metrics["North"]
    assert "unique_vehicles" in metrics["South"]
    assert metrics["North"]["duration_seconds"] > 0
    assert metrics["South"]["duration_seconds"] > 0
    # Unprovided approaches must have the baseline minimum note
    assert "note" in metrics["East"]
    assert "note" in metrics["West"]


# 4. Simultaneous photo and video inference
def test_simultaneous_photo_and_video_inference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    raw_detector = ConcurrentDetectionDetectorModel(simulated_latency=0.02)
    safe_model = ThreadSafeYOLO(raw_detector, get_inference_lock())
    monkeypatch.setattr(detection, "_model", safe_model)

    dummy_image_path = tmp_path / "junction.jpg"
    cv2.imwrite(str(dummy_image_path), np.zeros((480, 640, 3), dtype=np.uint8))

    dummy_video_path = _create_synthetic_mp4(tmp_path / "clip.mp4")
    out_dir = tmp_path / "out"

    photo_res = [None]
    video_res = [None]
    exceptions = []

    def run_photo():
        try:
            photo_res[0] = detection.analyse_image(dummy_image_path, out_dir)
        except Exception as e:
            exceptions.append(e)

    def run_video():
        try:
            video_res[0] = detection.analyse_video(dummy_video_path, out_dir)
        except Exception as e:
            exceptions.append(e)

    t1 = threading.Thread(target=run_photo)
    t2 = threading.Thread(target=run_video)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not exceptions, f"Exceptions occurred: {exceptions}"
    assert photo_res[0] is not None
    assert video_res[0] is not None
    assert raw_detector.max_concurrency == 1
    assert not raw_detector.race_detected


# 5. Exception during prediction
def test_exception_during_prediction(monkeypatch: pytest.MonkeyPatch):
    class ExplodingModel:
        def predict(self, *args, **kwargs):
            raise RuntimeError("Hardware/CUDA failure during forward pass")

    shared_lock = threading.RLock()
    safe_model = ThreadSafeYOLO(ExplodingModel(), shared_lock)

    # Calling predict raises the error
    with pytest.raises(RuntimeError, match="Hardware/CUDA failure"):
        safe_model.predict([np.zeros((10, 10, 3))])

    # Lock must be released immediately despite exception
    acquired = shared_lock.acquire(blocking=False)
    assert acquired, "Inference lock must be released when predict() raises an exception"
    shared_lock.release()


# 6. Cancellation during prediction
def test_cancellation_during_prediction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    raw_detector = ConcurrentDetectionDetectorModel(simulated_latency=0.01)
    safe_model = ThreadSafeYOLO(raw_detector, get_inference_lock())
    monkeypatch.setattr(detection, "_model", safe_model)

    dummy_video = _create_synthetic_mp4(tmp_path / "cancel_clip.mp4")
    out_dir = tmp_path / "out"

    # Cancellation check returning True
    cancelled = True
    with pytest.raises(RuntimeError, match="Video processing cancelled"):
        analyse_directional_video_clip(
            dummy_video,
            "North",
            out_dir,
            sample_fps=2.0,
            cancellation_check=lambda: cancelled,
        )

    # Inference lock must not be held
    acquired = get_inference_lock().acquire(blocking=False)
    assert acquired, "Inference lock must not remain held on cancellation"
    get_inference_lock().release()


# 7. Lock release after failure
def test_lock_release_after_failure_allows_subsequent_workers():
    call_num = 0
    lock = threading.RLock()

    class FlakyModel:
        def predict(self, *args, **kwargs):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                raise ValueError("Transient inference failure")
            return [FakeResult()]

    safe_model = ThreadSafeYOLO(FlakyModel(), lock)

    # First call fails
    with pytest.raises(ValueError, match="Transient inference failure"):
        safe_model.predict("bad")

    # Second call succeeds without deadlock
    res = safe_model.predict("good")
    assert len(res) == 1


# 8. Model initialization count
def test_model_initialization_count(monkeypatch: pytest.MonkeyPatch):
    init_counter = 0

    class MockYOLO:
        def __init__(self, path):
            nonlocal init_counter
            init_counter += 1
            self.names = {0: "person", 2: "car"}

        def predict(self, *args, **kwargs):
            return [FakeResult()]

    # Reset detection._model to None
    monkeypatch.setattr(detection, "_model", None)
    monkeypatch.setattr(detection, "get_detection_status", lambda: {"missing_dependencies": [], "model_available": True, "model_name": "yolov8n.pt"})
    monkeypatch.setattr(detection, "_available_model_path", lambda: Path("yolov8n.pt"))
    monkeypatch.setattr(detection, "verify_model_integrity", lambda p: True)

    import ultralytics
    monkeypatch.setattr(ultralytics, "YOLO", MockYOLO)

    # Concurrently request model from 10 threads
    models = [None] * 10

    def get_worker(i):
        models[i] = _get_model()

    threads = [threading.Thread(target=get_worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly 1 model initialization must have occurred
    assert init_counter == 1
    # All threads received the identical thread-safe singleton
    first = models[0]
    assert all(m is first for m in models)


# 9. Repeated video-analysis jobs
def test_repeated_video_analysis_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    raw_detector = ConcurrentDetectionDetectorModel(simulated_latency=0.01)
    safe_model = ThreadSafeYOLO(raw_detector, get_inference_lock())
    monkeypatch.setattr(detection, "_model", safe_model)

    video_dir = tmp_path / "repeated_cams"
    paths = {
        "North": _create_synthetic_mp4(video_dir / "north.mp4"),
        "South": _create_synthetic_mp4(video_dir / "south.mp4"),
    }
    out_dir = tmp_path / "out"

    # Run 3 consecutive jobs
    for i in range(3):
        res = analyse_multi_directional_videos(paths, out_dir, sample_fps=2.0)
        assert res["total_count"] >= 0
        assert "North" in res["counts"]

    # Verify no race conditions across consecutive runs
    assert raw_detector.max_concurrency == 1
    assert not raw_detector.race_detected


# 10. Model hash verification rejects corrupted models
def test_model_hash_verification_rejects_corrupted_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_weights = tmp_path / "yolov8n.pt"
    fake_weights.write_bytes(b"CORRUPTED_WEIGHTS_CONTENT")

    monkeypatch.setattr(detection, "_model", None)
    monkeypatch.setattr(detection, "get_detection_status", lambda: {"missing_dependencies": [], "model_available": True, "model_name": "yolov8n.pt"})
    monkeypatch.setattr(detection, "_available_model_path", lambda: fake_weights)

    # Force integrity check to fail
    monkeypatch.setattr(detection, "verify_model_integrity", lambda p: False)

    with pytest.raises(ModelUnavailableError, match="Model integrity verification failed"):
        _get_model()
