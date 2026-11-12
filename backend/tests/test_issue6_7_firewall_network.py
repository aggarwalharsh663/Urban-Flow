from __future__ import annotations

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
VITE_CONFIG = REPO_ROOT / "frontend" / "vite.config.ts"
SETUP_PS1 = BASE_DIR / "setup.ps1"
RUN_BACKEND_BAT = BASE_DIR / "run-backend.bat"
RUN_BACKEND_PS1 = BASE_DIR / "run-backend.ps1"
RUN_FRONTEND_BAT = REPO_ROOT / "frontend" / "run-frontend.bat"
START_BAT = REPO_ROOT / "start.bat"


def test_vite_config_loopback_isolation_issue6():
    """
    Issue 6: Verify vite.config.ts explicitly binds to 127.0.0.1 (IPv4 loopback)
    so that Windows Defender Firewall never prompts for Public/Private network access.
    """
    assert VITE_CONFIG.is_file(), f"vite.config.ts missing at {VITE_CONFIG}"
    content = VITE_CONFIG.read_text(encoding="utf-8")

    assert 'host: "127.0.0.1"' in content, "vite.config.ts must explicitly configure host as '127.0.0.1'"
    assert "port: 5174" in content, "vite.config.ts must configure port 5174"
    assert "strictPort: true" in content, "vite.config.ts must enforce strictPort: true"


def test_scripts_bind_exclusively_to_loopback_issue6():
    """
    Issue 6: Ensure all launch scripts bind exclusively to 127.0.0.1 and never 0.0.0.0.
    """
    scripts = [RUN_BACKEND_BAT, RUN_BACKEND_PS1, RUN_FRONTEND_BAT, START_BAT]
    for script in scripts:
        assert script.is_file(), f"Missing script: {script}"
        text = script.read_text(encoding="utf-8")
        assert "0.0.0.0" not in text, f"Script {script.name} must never bind to wildcard 0.0.0.0"
        assert "127.0.0.1" in text, f"Script {script.name} must bind explicitly to 127.0.0.1"


def test_setup_ps1_offline_check_and_firewall_handling_issue7():
    """
    Issue 7: Ensure setup.ps1 detects pre-installed offline dependencies before making
    outbound PyPI calls, uses bounded timeouts, and provides actionable firewall diagnostics.
    """
    assert SETUP_PS1.is_file(), f"Missing setup.ps1 at {SETUP_PS1}"
    content = SETUP_PS1.read_text(encoding="utf-8")

    # Offline check before network calls
    assert "DepsCheck" in content, "setup.ps1 must check if dependencies are already satisfied offline"
    assert "already installed and satisfied offline" in content

    # Bounded timeouts to prevent firewall hangs
    timeout_matches = re.findall(r"--timeout\s+(\d+)", content)
    assert len(timeout_matches) > 0, "setup.ps1 must specify bounded pip timeouts"
    for t in timeout_matches:
        assert int(t) <= 60, f"pip timeout {t}s in setup.ps1 should be bounded (<= 60s) to prevent firewall hangs"

    # Actionable firewall diagnostics
    assert "firewall" in content.lower(), "setup.ps1 must provide diagnostics if blocked by firewall"


def test_start_bat_graceful_npm_handling_issue7():
    """
    Issue 7: Verify start.bat gracefully detects npm install failures without crashing
    when behind a corporate/offline firewall.
    """
    assert START_BAT.is_file(), f"Missing start.bat at {START_BAT}"
    content = START_BAT.read_text(encoding="utf-8")

    assert "npm install" in content
    assert "errorlevel" in content
    assert "firewall blocks outbound" in content
