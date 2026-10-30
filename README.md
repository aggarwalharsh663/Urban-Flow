# Adaptive Traffic Signal System

A full-stack decision-support prototype that can use the Google Gemini API for image understanding and falls back automatically to OpenCV with a locally stored YOLOv8 model. The deterministic Python planner recommends a fair 120-second green-time allocation. Nothing in this project connects to or controls real traffic signals. Gemini is optional: without its API key, analysis stays on this computer.

## Team Details:-
Frontend:-Divy Dixit and Prisha Singhvi
Backend:- Harsh Aggarwal
Logo Designing:- Kavy Agarwal

## Prerequisites

- Windows 10/11 (commands below use PowerShell), macOS, or Linux.
- Python **3.10 or newer**. The setup script uses the installed Python interpreter and creates an isolated virtual environment.
- Node.js 20 or newer and npm.
- A local YOLOv8 weights file for image/video analysis. The detector prefers `yolov8m.pt`, then `yolov8s.pt`, then `yolov8n.pt`. Simulated-data mode does not need model weights.
- Optional: a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey). If configured, uploaded image content (or the representative video frame) is sent to Google first; local YOLO is tried automatically if Gemini is unavailable or fails.
- For Windows, install the Python package dependencies in a virtual environment. A CUDA-capable GPU is optional; CPU inference works but may be slower.

## Project layout

```text
backend/
  main.py
  services/
    detection.py
    gemini.py
    planning.py
  uploads/       # uploaded originals and annotated frames, stored locally
  reports/       # generated JSON signal plans, stored locally
  requirements.txt
frontend/
  src/
  package.json
```

## Setup

### 1. Install the Python backend

From the project root, open PowerShell and run the launcher:

```powershell
.\start-local.ps1
```

On Windows, double-click `start.bat` in the project folder to start the frontend. It runs `frontend\run-frontend.bat` in the current window; keep that window open while using the app. The frontend opens at **http://127.0.0.1:5174** and targets the API at **http://127.0.0.1:8001**, so it does not use another Urban Flow instance on the default ports.

```powershell
.\backend\setup.ps1
```

If PowerShell prevents running scripts, allow them only for the current terminal, then run the command again:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\start-local.ps1
```

### 2. Put YOLOv8 weights on this computer

Download an official Ultralytics YOLOv8 pretrained model from [the YOLOv8 model page](https://docs.ultralytics.com/models/yolov8/). The detector checks local files in this order: `yolov8m.pt`, `yolov8s.pt`, then `yolov8n.pt`. For the most capable supported option, use `yolov8m.pt`. You can also download the nano fallback in PowerShell from the `backend` directory:

```powershell
Invoke-WebRequest -Uri "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt" -OutFile ".\yolov8n.pt"
```

Save/keep the file as:

```text
backend/yolov8n.pt
```

Save the downloaded file directly in `backend\` under its original model filename. The detector weights are stored locally and loaded by Ultralytics for inference on this computer. All supported weights are ignored by Git and are not included in the source. The installer uses the USTC PyPI mirror because the default PyPI host may be unreachable on some networks. If weights are absent, image/video analysis still works when Gemini is configured; otherwise, the API returns an explicit setup error. Simulated mode remains available.

The dashboard reports backend, vision-package, model, and optional Gemini readiness. If dependencies are missing, run `.\backend\setup.ps1` and restart the backend.

### 2a. Optional Gemini API setup

1. Create an API key in [Google AI Studio](https://aistudio.google.com/apikey).
2. In PowerShell from the project root, run `Copy-Item .\backend\.env.example .\backend\.env`, then set `GEMINI_API_KEY` in `backend\.env` to your key. Keep this key private; `.env` is ignored by Git and the key is only read by the backend.
3. Optionally change `GEMINI_MODEL` in `backend\.env`; the default is `gemini-3.8-flash`.
4. Run `.\backend\setup.ps1` to install the added Python environment-file dependency, then restart the backend.

When the key is set, Gemini is tried first for uploaded images or one middle frame from a video. If its request, response, or configured access fails, the backend silently proceeds with local YOLO and the web page displays the successful local result rather than a Gemini error. If both providers fail, the backend returns an actionable analysis error. Simulations never use Gemini. The UI clearly indicates when uploaded media may be sent to Google. To use local processing only, remove/blank `GEMINI_API_KEY` and restart the backend.

### 3. Install frontend dependencies

In a second terminal:

```powershell
cd frontend
npm install
```

The UI uses Tailwind CSS through the local Vite build. The Gemini key is never sent to the frontend.

## Run locally

The root launcher starts the frontend only. Start the backend separately if it is available. You can start the backend manually:

```powershell
cd backend
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd frontend
$env:VITE_API_URL = "http://127.0.0.1:8001"
npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Open **http://127.0.0.1:5174**. The frontend expects its backend at **http://127.0.0.1:8001**. The website retries the API connection every five seconds. If a server is stopped, close its terminal and run the corresponding launcher again.

If the frontend API server is not on `http://127.0.0.1:8000`, set `VITE_API_URL` in the frontend environment before starting Vite. Restart Vite after changing environment variables.

Use the header control to switch between dark and light views. The preference is stored in this browser. The supplied UrbanFlow wordmark is kept locally in `frontend/public/`, with a light-background version and a recolored transparent version for dark mode.

## Demo workflow

1. **Image:** choose a JPG/JPEG/JPE/PNG junction image, inspect its preview, and select **Analyse traffic**. When configured, Gemini is tried first; otherwise or if it fails, local YOLO combines a full-frame pass with overlapping high-resolution tiles. Both modes draw boxes for cars, motorcycles, buses, and trucks. Review the results and correct the four direction totals when a model misses or double-counts vehicles; applying the correction recalculates and saves the signal plan.
2. **Video:** choose an MP4 and run the same analysis. To avoid counting a moving vehicle repeatedly without tracking, this prototype analyses one representative middle frame and annotates that frame. With Gemini enabled, that frame (not the entire video) is sent to Google. The original video is stored locally.
3. **Simulated counts:** switch to **Simulated data**, choose Balanced traffic, Heavy North traffic, Rush hour, or Low night traffic, or enter counts for each direction, then run the simulation. Simulations work without model weights.
4. Review the signal plan, set or edit the junction name, inspect the counts, annotated frame, chart, explanation, and cycle summary, and download a Markdown report.

Uploads and annotated frames are written under `backend/uploads/`; each generated plan is saved as a JSON file under `backend/reports/`. These local files are not automatically cleaned up. If Gemini is enabled, image bytes or the extracted video frame also leave the computer for processing by Google.

## Direction zones and signal logic

Direction is estimated from each detected box centre's nearest image edge (top=North, bottom=South, right=East, left=West). Gemini-proposed boxes use the same deterministic direction assignment. YOLOv8 combines a 1280-pixel full-frame pass with overlapping 960-pixel tiles and merges overlapping boxes. Overhead views, small vehicles, occlusion, and unusual camera placement can still result in missed or duplicate detections, so users can review and correct direction totals before using the plan. Zone assignment is isolated in `backend/services/detection.py` so configurable rectangles/polygons can be added later.

`calculate_green_times` in `backend/services/planning.py` is deterministic and separate from the model. It allocates the configured cycle time (default 120 seconds), with an adaptive floor and cap for each approach; the remaining time is distributed proportionally to vehicle counts. When counts are equal, green time is divided evenly (e.g. 30 seconds per direction on a 120-second cycle). Each approach also reports its yellow transition (3s) and red light timing (87s red, 90s total red+yellow wait time), keeping the total cycle at exactly 120 seconds.

## API

- `GET /api/health` — local API, YOLO model, and Gemini configuration availability (never reveals the key).
- `POST /api/analyse-image` — multipart field `file`, JPG/JPEG/PNG.
- `POST /api/analyse-video` — multipart field `file`, MP4.
- `POST /api/calculate-signal-plan` — JSON `{ "junction_name": "Example", "counts": { "North": 1, "South": 2, "East": 3, "West": 4 } }`.
- `POST /api/simulate` — same JSON shape, stored as a simulated report.
- `GET /api/reports/{report_id}` — fetch a locally stored signal plan.
- `PUT /api/reports/{report_id}/counts` — save visually reviewed direction counts and recalculate its plan.
- `GET /uploads/{filename}` — view locally stored original/annotated assets.

## Safety, limitations, and future work

- This is a decision-support prototype. It does **not** directly control real traffic lights.
- Gemini and YOLO detections and approach assignments can be inaccurate in poor weather, darkness, occlusion, crowded scenes, or unusual camera placement. Review counts before using a plan.
- Gemini-enabled image analysis sends the selected image to Google; video analysis sends one extracted middle frame. Configure a key only if this data sharing is acceptable.
- Video mode analyses a single middle-frame snapshot; it does not track vehicles or estimate flow over time. The nearest image edge is only a simple proxy for its approach direction.
- The deterministic green-time calculation is an illustrative rule, not a validated traffic-engineering model. Yellow/all-red values and cycle assumptions are demonstration values only.
- Real deployment requires traffic-engineering and authority approval, pedestrian phases, emergency-vehicle priority, accessibility provisions, hardware fail-safes, secure operational design, extensive testing, and applicable regulatory review.
- Planned improvements include vehicle tracking across video frames and UI-configurable road zones. Do not use the recommendations as live signal-control instructions.
