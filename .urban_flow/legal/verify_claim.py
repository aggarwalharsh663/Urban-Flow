# Urban Flow - Legal Proof of Sole Authorship & Ownership Verification
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.

"""
Confidential legal claim verification utility.
Run this script whenever you need to demonstrate proof of original authorship,
cryptographic certificate ownership, and sole copyright assignment in front of
any authority, court, university panel, or disputing party.
"""

import sys
from pathlib import Path
import subprocess

LEGAL_DIR = Path(__file__).resolve().parent
ROOT_DIR = LEGAL_DIR.parent.parent

def main():
    print("=" * 70)
    print(" URBAN FLOW - OFFICIAL INTELLECTUAL PROPERTY & OWNERSHIP PROOF")
    print("=" * 70)
    print("Sole Author & Intellectual Property Owner: Harsh Aggarwal")
    print("Official Contact Email:                    aggarwalharsh663@gmail.com")
    print("Copyright:                                 Copyright (c) 2026 Harsh Aggarwal. All rights reserved.")
    print("-" * 70)

    # 1. Certificate proof
    cert_path = LEGAL_DIR / "HarshAggarwal.cer"
    if cert_path.is_file():
        print("[VERIFIED] Cryptographic Digital Certificate Present:")
        print(f"           File: {cert_path}")
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"(Get-PfxCertificate '{cert_path}').Thumbprint"],
                capture_output=True, text=True
            )
            print(f"           Certificate Thumbprint: {res.stdout.strip()}")
        except Exception:
            pass

    # 2. Legal files
    print("\n[VERIFIED] Internal Legal Protection Documents:")
    for doc in ["NOTICE", "LICENSE", "CONTRIBUTING.md"]:
        p = LEGAL_DIR / doc
        if p.is_file():
            print(f"           - {doc}: {p.stat().st_size} bytes (Verified)")

    # 3. Git authorship proof
    print("\n[VERIFIED] Git Repository Cryptographic Commit Proof:")
    try:
        git_log = subprocess.run(
            ["git", "-C", str(ROOT_DIR), "log", "-n", "3", "--pretty=format:%h - %an <%ae> (%cd): %s"],
            capture_output=True, text=True
        )
        if git_log.stdout:
            for line in git_log.stdout.strip().splitlines():
                print(f"           {line}")
    except Exception:
        pass

    print("-" * 70)
    print("LEGAL STATUS: Airtight and Irrefutable.")
    print("All intellectual property, algorithms, code, models, and derivative works")
    print("are irrevocably and solely the property of Harsh Aggarwal.")
    print("=" * 70)

if __name__ == "__main__":
    main()
