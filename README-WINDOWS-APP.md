# Urban Flow - Windows Desktop Application

This is the standalone **Windows Desktop Application** conversion of **Urban Flow** (Adaptive Traffic Signal System).

---

## 🚀 How to Run the App

You have three easy ways to launch the Windows app:

1. **Desktop Shortcut**:
   Double-click the **`Urban Flow App`** shortcut directly on your Windows Desktop.

2. **Native Executable**:
   Double-click **`Urban Flow.exe`** in this folder (`c:\Users\User\OneDrive\Desktop\Urban Flow Windows App\Urban Flow.exe`).
   * Runs natively as a clean, windowed application with zero console clutter.

3. **Batch Launcher**:
   Double-click **`Urban Flow.bat`** in this folder if you want to view startup logs in a command prompt window.

---

## ✨ Features & Architecture

* **Identical UI & Experience**:
  The user interface is 100% identical to the web app (Dashboard, Analysis, Safety & Limits, charts, cycle timing summaries, and real-time detection views).
* **Native Desktop Window**:
  Runs in its own dedicated, native Windows frame (`1480x920`), auto-hiding menus, with dark theme integration and custom Urban Flow app branding.
* **Automated Background Management**:
  * Automatically spins up the Python FastAPI backend on port `8000` with local YOLOv8 weights (`yolov8m.pt`, `yolov8s.pt`, `yolov8n.pt`).
  * Automatically connects to the frontend interface on port `5174`.
  * **Zero orphan processes**: Closing the desktop app window automatically and cleanly terminates all background services.
* **Persistent Uploads & Reports**:
  All uploaded images, annotated bounding box outputs, and calculated reports are saved and accessible locally.
