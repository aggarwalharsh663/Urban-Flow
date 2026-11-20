#!/usr/bin/env python3
"""
Urban Flow - Git Hooks Setup
Copyright (c) 2026 Harsh Aggarwal. All rights reserved.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK_SRC = ROOT / ".git" / "hooks" / "pre-commit"

HOOK_CONTENT = """#!/bin/sh
# Urban Flow - Automated Pre-Commit Copyright Enforcer
# Copyright (c) 2026 Harsh Aggarwal. All rights reserved.

PYTHON_EXE=""
if [ -f "backend/python/python.exe" ]; then
    PYTHON_EXE="backend/python/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_EXE="python"
fi

if [ -n "$PYTHON_EXE" ]; then
    "$PYTHON_EXE" scripts/apply_copyright.py --check-staged
fi
exit 0
"""

def setup():
    hook_dir = ROOT / ".git" / "hooks"
    if hook_dir.is_dir():
        hook_path = hook_dir / "pre-commit"
        hook_path.write_text(HOOK_CONTENT, encoding="utf-8")
        print("Pre-commit copyright protection hook installed successfully.")

if __name__ == "__main__":
    setup()
