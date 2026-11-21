# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

from __future__ import annotations

import concurrent.futures
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ipc_worker import (
    BoundedCancellationRegistry,
    CANCELLED_REQUESTS,
    cancel_request,
    is_request_cancelled,
    pop_cancelled_request,
    process_ipc_request,
)
import security_config
from security_config import OperationCancelledError, get_writable_data_dir
from services.detection import analyse_image, analyse_video, _detect, get_inference_lock
from services.gemini import analyse_with_gemini, GeminiAnalysisError


@pytest.fixture(autouse=True)
def clean_registry():
    CANCELLED_REQUESTS.clear()
    yield
    CANCELLED_REQUESTS.clear()


class MockResult:
    def __init__(self, frame):
        self.boxes = []
        self.names = {0: "person", 2: "car"}
        self._frame = frame

    def plot(self):
        return self._frame.copy()


class MockModel:
    def predict(self, frame, **kwargs):
        return [MockResult(frame)]


@pytest.fixture(autouse=True)
def stub_yolo_model(monkeypatch):
    """Hermetic unit tests without requiring real YOLO weights on disk."""
    import services.detection
    mock_model = MockModel()
    monkeypatch.setattr(services.detection, "_get_model", lambda: mock_model)
    return mock_model


@pytest.fixture(autouse=True)
def isolate_ipc_dirs(tmp_path: Path, monkeypatch):
    """Isolate IPC analysis from real application data directories."""
    import ipc_worker
    test_upload = tmp_path / "ipc_uploads"
    test_report = tmp_path / "ipc_reports"
    test_upload.mkdir(parents=True, exist_ok=True)
    test_report.mkdir(parents=True, exist_ok=True)
    test_storage = security_config.StorageManager(upload_dir=test_upload, report_dir=test_report)
    monkeypatch.setattr(ipc_worker, "UPLOAD_DIR", test_upload)
    monkeypatch.setattr(ipc_worker, "REPORT_DIR", test_report)
    monkeypatch.setattr(ipc_worker, "GLOBAL_STORAGE_MANAGER", test_storage)


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    img_path = tmp_path / "test_junction.jpg"
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    # Draw simple road markings
    cv2.line(img, (320, 0), (320, 480), (255, 255, 255), 2)
    cv2.line(img, (0, 240), (640, 240), (255, 255, 255), 2)
    cv2.imwrite(str(img_path), img)
    return img_path


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    vid_path = tmp_path / "test_junction.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(vid_path), fourcc, 10.0, (320, 240))
    for i in range(20):
        frame = np.full((240, 320, 3), i * 10, dtype=np.uint8)
        out.write(frame)
    out.release()
    return vid_path


# 1. Video Cancellation Before Opening
def test_video_cancellation_before_opening(sample_video: Path, tmp_path: Path):
    with pytest.raises(OperationCancelledError) as exc_info:
        analyse_video(sample_video, tmp_path, cancellation_check=lambda: True)
    assert "cancelled" in str(exc_info.value).lower()


# 2. Video Cancellation During Frame Sampling
def test_video_cancellation_during_frame_sampling(sample_video: Path, tmp_path: Path):
    checks = 0

    def cancel_after_init():
        nonlocal checks
        checks += 1
        return checks >= 3

    with pytest.raises(OperationCancelledError) as exc_info:
        analyse_video(sample_video, tmp_path, cancellation_check=cancel_after_init)
    assert "cancelled" in str(exc_info.value).lower()


# 3. Video Cancellation During Inference
def test_video_cancellation_during_inference(sample_video: Path, tmp_path: Path):
    # Mock model predict to verify cancellation check immediately before inference
    cancelled = False

    def trigger_cancel():
        nonlocal cancelled
        cancelled = True
        return True

    with pytest.raises(OperationCancelledError):
        analyse_video(sample_video, tmp_path, cancellation_check=trigger_cancel)


# 4. Image Cancellation Before Opening
def test_image_cancellation_before_opening(sample_image: Path, tmp_path: Path):
    with pytest.raises(OperationCancelledError) as exc_info:
        analyse_image(sample_image, tmp_path, cancellation_check=lambda: True)
    assert "cancelled" in str(exc_info.value).lower()


# 5. Image Cancellation Before Inference
def test_image_cancellation_before_inference(sample_image: Path, tmp_path: Path):
    checks = 0

    def cancel_before_infer():
        nonlocal checks
        checks += 1
        return checks >= 2

    with pytest.raises(OperationCancelledError) as exc_info:
        analyse_image(sample_image, tmp_path, cancellation_check=cancel_before_infer)
    assert "cancelled" in str(exc_info.value).lower()


# 6. Detection Cancellation Before Writing File
def test_detection_cancellation_before_writing_file(tmp_path: Path):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    out_filename = "should_not_exist.jpg"

    # Mock _get_model predict to succeed, but cancel right before writing annotated frame
    with patch("services.detection._get_model") as mock_get_model:
        mock_model = MagicMock()
        mock_res = MagicMock()
        mock_res.boxes = []
        mock_model.predict.return_value = [mock_res]
        mock_get_model.return_value = mock_model

        with pytest.raises(OperationCancelledError):
            _detect(frame, tmp_path, out_filename, cancellation_check=lambda: True)

    assert not (tmp_path / out_filename).exists()


# 7. Cloud AI (Gemini) Cancellation Before Network Request
def test_gemini_cancellation_before_network(sample_image: Path, tmp_path: Path):
    with patch("urllib.request.urlopen") as mock_urlopen:
        with pytest.raises(OperationCancelledError):
            analyse_with_gemini(sample_image, tmp_path, video=False, cancellation_check=lambda: True)
        mock_urlopen.assert_not_called()


# 8. IPC Worker Single Image Cancellation Lifecycle
def test_ipc_worker_single_image_cancellation(sample_image: Path, monkeypatch):
    test_token = "test_ipc_token_sec_0123456789abcdef"
    monkeypatch.setenv("URBAN_FLOW_IPC_TOKEN", test_token)

    req_id = "req_cancel_image_01"
    # Pre-register cancellation
    cancel_request(req_id)

    req = {
        "id": req_id,
        "action": "analyse-image",
        "token": test_token,
        "scope": "inference:write",
        "data": {
            "image_path": str(sample_image),
            "junction_name": "Test Cancelled Junction",
        },
    }

    resp = process_ipc_request(req)
    assert resp["id"] == req_id
    assert resp["ok"] is True
    assert resp["result"] == {"cancelled": True}
    assert not is_request_cancelled(req_id)


# 9. IPC Worker Single Video Cancellation Lifecycle
def test_ipc_worker_single_video_cancellation(sample_video: Path, monkeypatch):
    test_token = "test_ipc_token_sec_0123456789abcdef"
    monkeypatch.setenv("URBAN_FLOW_IPC_TOKEN", test_token)

    req_id = "req_cancel_video_01"
    cancel_request(req_id)

    req = {
        "id": req_id,
        "action": "analyse-video",
        "token": test_token,
        "scope": "inference:write",
        "data": {
            "video_path": str(sample_video),
            "junction_name": "Test Cancelled Video",
        },
    }

    resp = process_ipc_request(req)
    assert resp["id"] == req_id
    assert resp["ok"] is True
    assert resp["result"] == {"cancelled": True}
    assert not is_request_cancelled(req_id)


# 10. Cancellation of Completed Request
def test_cancellation_of_completed_request(sample_image: Path, monkeypatch):
    test_token = "test_ipc_token_sec_0123456789abcdef"
    monkeypatch.setenv("URBAN_FLOW_IPC_TOKEN", test_token)

    req_id = "req_completed_01"
    req = {
        "id": req_id,
        "action": "analyse-image",
        "token": test_token,
        "scope": "inference:write",
        "data": {
            "file_path": str(sample_image),
            "junction_name": "Test Completed Junction",
        },
    }

    # Execute normally
    resp = process_ipc_request(req)
    assert resp["id"] == req_id
    assert resp["ok"] is True
    assert "report_id" in resp["result"]

    # Now cancel message arrives for this already-finished request
    cancel_request(req_id)
    assert is_request_cancelled(req_id)
    # Consuming it
    assert pop_cancelled_request(req_id)
    assert not is_request_cancelled(req_id)


# 11. Concurrent Requests with Selective Cancellation
def test_concurrent_requests_selective_cancellation(sample_image: Path, monkeypatch):
    test_token = "test_ipc_token_sec_0123456789abcdef"
    monkeypatch.setenv("URBAN_FLOW_IPC_TOKEN", test_token)

    req_id_cancel = "req_conc_cancel"
    req_id_ok = "req_conc_ok"

    cancel_request(req_id_cancel)

    req_cancel = {
        "id": req_id_cancel,
        "action": "analyse-image",
        "token": test_token,
        "scope": "inference:write",
        "data": {"file_path": str(sample_image)},
    }
    req_ok = {
        "id": req_id_ok,
        "action": "analyse-image",
        "token": test_token,
        "scope": "inference:write",
        "data": {"file_path": str(sample_image)},
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_cancel = executor.submit(process_ipc_request, req_cancel)
        f_ok = executor.submit(process_ipc_request, req_ok)

        res_cancel = f_cancel.result()
        res_ok = f_ok.result()

    assert res_cancel["ok"] is True
    assert res_cancel["result"] == {"cancelled": True}

    assert res_ok["ok"] is True
    assert "report_id" in res_ok["result"]
    assert res_ok["result"]["source"] == "image"


# 12. Normal Single Image and Video Analysis Without Cancellation Preserved
def test_normal_single_image_and_video_analysis(sample_image: Path, sample_video: Path, tmp_path: Path):
    # Image analysis without cancellation check
    img_res = analyse_image(sample_image, tmp_path)
    assert "counts" in img_res
    assert "annotated_filename" in img_res
    assert (tmp_path / img_res["annotated_filename"]).exists()

    # Video analysis without cancellation check
    vid_res = analyse_video(sample_video, tmp_path)
    assert "counts" in vid_res
    assert "annotated_filename" in vid_res
    assert (tmp_path / vid_res["annotated_filename"]).exists()
