import json
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BASE_DIR.parent / "frontend"


def test_w01_frontend_source_has_no_vite_api_token_references():
    """App.jsx must not read VITE_API_TOKEN, preventing Vite from inlining secrets (W-01)."""
    app_jsx = FRONTEND_DIR / "src" / "components" / "urbanflow" / "App.jsx"
    content = app_jsx.read_text(encoding="utf-8")
    assert "VITE_API_TOKEN" not in content
    assert "import.meta.env.VITE_API_TOKEN" not in content
    assert 'const API = "";' in content


def test_w01_run_frontend_bat_does_not_bake_vite_secrets():
    """run-frontend.bat must not export VITE_API_TOKEN or hardcoded absolute backend port (W-01)."""
    bat = FRONTEND_DIR / "run-frontend.bat"
    content = bat.read_text(encoding="utf-8")
    assert 'set "VITE_API_TOKEN=%%T"' not in content
    assert "VITE_API_URL=http://127.0.0.1:8000" not in content
    assert "URBAN_FLOW_DEV_TOKEN" in content


def test_w01_vite_proxy_configuration():
    """vite.config.ts must proxy /api and /uploads, attaching dev token server-side (W-01)."""
    vite_cfg = FRONTEND_DIR / "vite.config.ts"
    content = vite_cfg.read_text(encoding="utf-8")
    assert '"/api"' in content
    assert '"/uploads"' in content
    assert "URBAN_FLOW_DEV_TOKEN" in content
    assert "proxyReq.setHeader" in content


def test_w02_reader_thread_cancel_requires_authentication():
    """The live background _reader thread in ipc_worker.py must reject unauthenticated cancel requests (W-02)."""
    py_exe = sys.executable
    ipc_script = BASE_DIR / "ipc_worker.py"
    test_token = "test_ipc_session_secret_w02_token_987654321"

    env = os.environ.copy()
    env["URBAN_FLOW_IPC_TOKEN"] = test_token

    proc = subprocess.Popen(
        [py_exe, str(ipc_script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(BASE_DIR),
    )

    try:
        # Read the initial ready event
        ready_line = proc.stdout.readline()
        assert ready_line, "ipc_worker did not produce ready event"
        ready_data = json.loads(ready_line)
        assert ready_data.get("event") == "ready"

        # 1. Send unauthenticated cancel request
        unauth_req = {
            "id": "test-reader-unauth-cancel",
            "action": "cancel",
            "data": {"cancel_id": "job_to_cancel_unauth"},
        }
        proc.stdin.write(json.dumps(unauth_req) + "\n")
        proc.stdin.flush()

        unauth_resp_line = proc.stdout.readline()
        assert unauth_resp_line, "ipc_worker did not respond to unauth cancel"
        unauth_resp = json.loads(unauth_resp_line)
        assert unauth_resp["id"] == "test-reader-unauth-cancel"
        assert unauth_resp["ok"] is False
        assert "Unauthorized" in unauth_resp["error"]

        # 2. Send authenticated cancel request
        auth_req = {
            "id": "test-reader-auth-cancel",
            "action": "cancel",
            "token": test_token,
            "data": {"cancel_id": "job_to_cancel_auth"},
        }
        proc.stdin.write(json.dumps(auth_req) + "\n")
        proc.stdin.flush()

        auth_resp_line = proc.stdout.readline()
        assert auth_resp_line, "ipc_worker did not respond to auth cancel"
        auth_resp = json.loads(auth_resp_line)
        assert auth_resp["id"] == "test-reader-auth-cancel"
        assert auth_resp["ok"] is True
        assert auth_resp.get("result", {}).get("cancelled") is True

    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
