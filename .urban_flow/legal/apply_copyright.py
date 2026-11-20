#!/usr/bin/env python3
"""
Urban Flow - Automated Copyright & IP Assignment Enforcer
Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.

Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
Any additions, modifications, or contributed files to this project automatically
and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

AUTHOR = "Harsh Aggarwal"
EMAIL = "aggarwalharsh663@gmail.com"
YEAR = "2026"

COPYRIGHT_NOTICE_TEXT = f"""Urban Flow - Adaptive Traffic Signal System
Copyright (c) {YEAR} {AUTHOR} <{EMAIL}>. All rights reserved.

Original Author & Sole Intellectual Property Owner: {AUTHOR}
Any additions, modifications, or contributed files to this project automatically
and irrevocably vest all copyright and intellectual property rights solely in {AUTHOR}.
"""

# File extensions and their corresponding comment syntax
COMMENT_STYLES = {
    ".py": ("# ", "# ", "#"),
    ".sh": ("# ", "# ", "#"),
    ".bash": ("# ", "# ", "#"),
    ".js": ("/*\n", " * ", " */\n"),
    ".jsx": ("/*\n", " * ", " */\n"),
    ".ts": ("/*\n", " * ", " */\n"),
    ".tsx": ("/*\n", " * ", " */\n"),
    ".cjs": ("/*\n", " * ", " */\n"),
    ".mjs": ("/*\n", " * ", " */\n"),
    ".cs": ("/*\n", " * ", " */\n"),
    ".css": ("/*\n", " * ", " */\n"),
    ".html": ("<!--\n", "  ", "-->\n"),
    ".bat": ("REM ", "REM ", "REM"),
    ".cmd": ("REM ", "REM ", "REM"),
    ".ps1": ("# ", "# ", "#"),
}

IGNORE_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    "venv",
    "python",
    "test_out",
    ".pytest_cache",
    ".system_generated",
    ".user_uploaded",
    "scratch",
}

def format_header(ext: str) -> str:
    if ext not in COMMENT_STYLES:
        return ""
    start, middle, end = COMMENT_STYLES[ext]
    lines = COPYRIGHT_NOTICE_TEXT.strip().split("\n")

    if start == middle:  # Single-line style like # or REM
        return "\n".join(f"{start}{line}" if line else start.strip() for line in lines) + "\n\n"
    else:  # Block style like /* ... */ or <!-- ... -->
        body = "\n".join(f"{middle}{line}" if line else middle.rstrip() for line in lines)
        return f"{start}{body}\n{end}\n"

def process_file(file_path: Path) -> bool:
    ext = file_path.suffix.lower()
    if ext not in COMMENT_STYLES:
        return False

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False

    # Check if author's copyright is already present
    if f"Copyright (c) {YEAR} {AUTHOR}" in content or f"Copyright © {YEAR} {AUTHOR}" in content:
        return False

    header = format_header(ext)
    if not header:
        return False

    # Preserve shebang if present
    if content.startswith("#!"):
        lines = content.split("\n", 1)
        shebang = lines[0] + "\n"
        rest = lines[1] if len(lines) > 1 else ""
        new_content = shebang + header + rest
    else:
        new_content = header + content

    try:
        file_path.write_text(new_content, encoding="utf-8")
        print(f"[PROTECTED] Enforced copyright on: {file_path.relative_to(REPO_ROOT)}")
        return True
    except Exception as e:
        print(f"[ERROR] Could not update {file_path}: {e}")
        return False

def main():
    print("=" * 60)
    print(" Urban Flow - Copyright & Contributor IP Protection Engine")
    print(f" Copyright (c) {YEAR} {AUTHOR} <{EMAIL}>")
    print("=" * 60)

    staged_mode = "--check-staged" in sys.argv
    updated_count = 0

    if staged_mode:
        import subprocess
        try:
            res = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"], capture_output=True, text=True)
            files = [REPO_ROOT / line.strip() for line in res.stdout.splitlines() if line.strip()]
            for f in files:
                if f.is_file() and process_file(f):
                    updated_count += 1
                    subprocess.run(["git", "add", str(f)])
        except Exception as e:
            print(f"Error checking staged files: {e}")
    else:
        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
            for file in files:
                fpath = Path(root) / file
                if process_file(fpath):
                    updated_count += 1

    print(f"\nCompleted. Protected {updated_count} files with Harsh Aggarwal's copyright.")

if __name__ == "__main__":
    main()
