from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
APP_MANIFEST = REPO_ROOT / "app.manifest"
LAUNCHER_CS = REPO_ROOT / "launcher.cs"
BUILD_BAT = REPO_ROOT / "build-launcher.bat"
URBAN_FLOW_EXE = REPO_ROOT / "Urban Flow.exe"


def test_app_manifest_structure_and_as_invoker():
    """
    Issue 12: Verify app.manifest specifies requestedExecutionLevel 'asInvoker'
    so Windows UAC Appinfo does not mistake the application for an installer
    or require administrative elevation.
    """
    assert APP_MANIFEST.is_file(), f"Missing app.manifest at {APP_MANIFEST}"

    tree = ET.parse(APP_MANIFEST)
    root = tree.getroot()

    # Verify root namespace
    assert "urn:schemas-microsoft-com:asm.v1" in root.tag

    # Verify trustInfo -> security -> requestedPrivileges -> requestedExecutionLevel
    content = APP_MANIFEST.read_text(encoding="utf-8")
    assert "<trustInfo" in content
    assert "<requestedPrivileges" in content

    # Find requestedExecutionLevel
    rel_match = re.search(r'<requestedExecutionLevel\s+level="([^"]+)"\s+uiAccess="([^"]+)"', content)
    assert rel_match is not None, "requestedExecutionLevel element not found in app.manifest"
    level, ui_access = rel_match.group(1), rel_match.group(2)
    assert level == "asInvoker", f"Expected requestedExecutionLevel 'asInvoker', got '{level}'"
    assert ui_access.lower() == "false", f"Expected uiAccess 'false', got '{ui_access}'"

    # Verify OS compatibility for modern Windows (Windows 10 / 11)
    win10_guid = "{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"
    assert win10_guid in content, "Windows 10/11 supportedOS GUID missing from app.manifest"


def test_launcher_cs_metadata_avoids_installer_heuristics():
    """
    Issue 12: Ensure assembly metadata in launcher.cs avoids trigger words
    (such as 'setup', 'installer', 'patch') that trigger legacy Windows
    Installer Detection heuristics.
    """
    assert LAUNCHER_CS.is_file(), f"Missing launcher.cs at {LAUNCHER_CS}"
    code = LAUNCHER_CS.read_text(encoding="utf-8")

    # Extract assembly metadata values
    attributes = re.findall(r'\[assembly:\s*(Assembly[A-Za-z]+)\("([^"]*)"\)\]', code)
    assert len(attributes) > 0, "No assembly attributes found in launcher.cs"

    forbidden_triggers = ["installer", "setup", "patch", "update utility"]
    for attr_name, attr_val in attributes:
        lower_val = attr_val.lower()
        for trigger in forbidden_triggers:
            assert trigger not in lower_val, (
                f"Attribute {attr_name}='{attr_val}' contains installer heuristic trigger '{trigger}'"
            )


def test_build_launcher_bat_embeds_manifest():
    """
    Issue 12: Verify build-launcher.bat passes /win32manifest:app.manifest to csc.exe.
    """
    assert BUILD_BAT.is_file(), f"Missing build-launcher.bat at {BUILD_BAT}"
    bat_content = BUILD_BAT.read_text(encoding="utf-8")
    assert "/win32manifest:app.manifest" in bat_content, (
        "build-launcher.bat must embed app.manifest via /win32manifest flag"
    )


def test_urban_flow_exe_contains_embedded_manifest_with_as_invoker():
    """
    Issue 12: Verify Urban Flow.exe is a valid PE binary with the embedded
    UAC manifest specifying requestedExecutionLevel asInvoker.
    """
    assert URBAN_FLOW_EXE.is_file(), f"Urban Flow.exe not found at {URBAN_FLOW_EXE}"

    with open(URBAN_FLOW_EXE, "rb") as f:
        exe_bytes = f.read()

    # Verify DOS MZ header
    assert exe_bytes[:2] == b"MZ", "Urban Flow.exe does not have valid MZ DOS header"

    # Verify PE signature
    e_lfanew = int.from_bytes(exe_bytes[0x3C:0x40], byteorder="little")
    assert exe_bytes[e_lfanew : e_lfanew + 4] == b"PE\x00\x00", "Invalid PE signature offset"

    # Verify embedded manifest elements
    assert b"<requestedExecutionLevel" in exe_bytes, "Missing <requestedExecutionLevel> in Urban Flow.exe"
    assert b'level="asInvoker"' in exe_bytes, "Urban Flow.exe manifest does not specify level='asInvoker'"
    assert b'uiAccess="false"' in exe_bytes, "Urban Flow.exe manifest does not specify uiAccess='false'"
    assert b"{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}" in exe_bytes, (
        "Urban Flow.exe manifest missing Windows 10/11 compatibility GUID"
    )
