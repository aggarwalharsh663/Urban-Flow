#!/usr/bin/env bash
# Urban Flow - Adaptive Traffic Signal System
# Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
#
# Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
# Any additions, modifications, or contributed files to this project automatically
# and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.

set -e

echo "=== Setting up Urban Flow Cloud Development Environment ==="

# Install system dependencies required for OpenCV and YOLOv8
echo "Installing system dependencies..."
sudo apt-get update && sudo apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    ffmpeg

# Install Python dependencies
echo "Installing Python backend dependencies..."
python -m pip install --upgrade pip
pip install -r backend/requirements.txt

# Install Node / frontend dependencies
echo "Installing frontend dependencies..."
cd frontend
npm install
cd ..

# Initialize git hooks for copyright protection
if [ -f .urban_flow/legal/setup_git_hooks.py ]; then
    python .urban_flow/legal/setup_git_hooks.py || true
fi

echo "=== Urban Flow Cloud Development Environment Ready ==="
