import io
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

import security_config
from main import app, UPLOAD_DIR

client = TestClient(app)
VALID_TOKEN = security_config.get_or_create_api_token()
AUTH_HEADERS = {"X-API-Token": VALID_TOKEN}


def create_real_png_bytes(width=100, height=100) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(73, 109, 137))
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_reject_html_upload():
    """HTML upload attempts must be rejected."""
    html_content = b"<html><body><script>alert(1)</script></body></html>"
    response = client.post(
        "/api/analyse-image",
        headers=AUTH_HEADERS,
        files={"file": ("exploit.html", html_content, "text/html")},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.text


def test_reject_exe_upload():
    """Executable upload attempts must be rejected."""
    exe_content = b"MZ\x90\x00\x03\x00\x00\x00"
    response = client.post(
        "/api/analyse-image",
        headers=AUTH_HEADERS,
        files={"file": ("malware.exe", exe_content, "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.text


def test_reject_fake_png_with_html_payload():
    """Fake PNG containing HTML payload must be rejected by magic bytes."""
    fake_png = b"<html><head><script>alert('xss')</script></head></html>"
    response = client.post(
        "/api/analyse-image",
        headers=AUTH_HEADERS,
        files={"file": ("fake.png", fake_png, "image/png")},
    )
    assert response.status_code == 400
    assert "File content does not match expected format" in response.text or "magic signature" in response.text


def test_reject_fake_mp4():
    """Fake MP4 must be rejected by magic bytes."""
    fake_mp4 = b"RIFF\x00\x00\x00\x00AVI LIST"
    response = client.post(
        "/api/analyse-video",
        headers=AUTH_HEADERS,
        files={"file": ("fake.mp4", fake_mp4, "video/mp4")},
    )
    assert response.status_code == 400
    assert "File content does not match" in response.text or "magic signature" in response.text


def test_reject_oversized_upload():
    """Uploads exceeding the 100 MB limit must be rejected with HTTP 413."""
    # We can mock chunk stream or test the size check limit directly
    header = b"\x89PNG\r\n\x1a\n"
    # Using 101 MB virtual generator
    class LargeUpload(io.RawIOBase):
        def __init__(self, size):
            self.size = size
            self.read_bytes = 0

        def readinto(self, b):
            if self.read_bytes >= self.size:
                return 0
            n = min(len(b), self.size - self.read_bytes)
            if self.read_bytes == 0 and n >= 8:
                b[:8] = header
                b[8:n] = b"\x00" * (n - 8)
            else:
                b[:n] = b"\x00" * n
            self.read_bytes += n
            return n

    large_stream = LargeUpload(101 * 1024 * 1024)
    response = client.post(
        "/api/analyse-image",
        headers=AUTH_HEADERS,
        files={"file": ("large.png", large_stream, "image/png")},
    )
    assert response.status_code == 413
    assert "exceeds" in response.text


def test_temporary_files_cleaned_up_on_failure():
    """Temporary files must be deleted on validation failure."""
    count_before = len(list(UPLOAD_DIR.glob(".tmp_*")))
    fake_png = b"Not A Real PNG Content"
    client.post(
        "/api/analyse-image",
        headers=AUTH_HEADERS,
        files={"file": ("cleanup_test.png", fake_png, "image/png")},
    )
    count_after = len(list(UPLOAD_DIR.glob(".tmp_*")))
    assert count_after == count_before


def test_serve_upload_security_headers():
    """Serving uploaded content must include nosniff, CSP sandbox, and block execution."""
    real_png = create_real_png_bytes(50, 50)
    # Save a test image in UPLOAD_DIR
    test_filename = "test_safe_image.png"
    (UPLOAD_DIR / test_filename).write_bytes(real_png)

    try:
        response = client.get(f"/uploads/{test_filename}")
        assert response.status_code == 200
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert "sandbox" in response.headers.get("content-security-policy", "")
        assert "inline" in response.headers.get("content-disposition", "")
    finally:
        (UPLOAD_DIR / test_filename).unlink(missing_ok=True)


def test_serve_upload_rejects_html_and_non_media():
    """Attempts to request HTML or unexpected files from /uploads must fail."""
    response = client.get("/uploads/index.html")
    assert response.status_code == 404
