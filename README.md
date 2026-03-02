# Pushup Counter — AI Fitness Tracker

An advanced, real-time pushup counter and form analyzer powered by MediaPipe pose estimation, OpenCV, and a Flask/WebSocket backend.

## Features

- **Real-Time Body Tracking**: Uses MediaPipe to detect comprehensive body landmarks in real time.
- **Accurate Form Analysis**:
  - Calculates elbow angles (up and down position).
  - Validates straight back/legs to enforce good form.
  - Ensures your body maintains a horizontal pitch angle.
- **Adjustable Parameters & Tolerances**:
  - Tweak sensitivity (Down Angle, Up Angle, Leg Straightness).
  - Customize the required horizontal range min/max bounds directly in the browser UI.
  - Setup wait and cooldown times for pushup registration.
- **Live Visuals**: Immersive web interface overlaying telemetry metrics onto your camera feed.
- **Multi-Camera Support**: Seamlessly detect and switch between webcams directly from the interface.
- **User Profiles**: Three independently configurable profiles, each storing their own angle thresholds and settings.
- **Manual Count Controls**: Increment, decrement, or directly set the rep count at any time. Quick-adjust buttons (+/− 10, 20, 50) with a toggleable add/subtract mode for fast corrections.
- **OBS Streaming Overlay** *(port 5001)*: A transparent browser-source widget showing the live rep count, current state badge, and a real-time AI pose preview — skeleton lines only, no camera feed — so viewers can see exactly what the model is tracking.
- **Debug Log Panel**: Toggleable in-browser log showing every rep decision with angle data and rejection reasons.

## Ports

| Port | Purpose |
|------|---------|
| `5000` | Main control interface (camera feed, settings, counters) |
| `5001` | OBS browser-source overlay (transparent background, rep counter + pose preview) |

## Prerequisites

Before getting started, make sure you have the following installed on your system:
- Python 3.8+
- [pip](https://pip.pypa.io/en/stable/installation/)

### macOS: Grant Camera Access to Terminal

On macOS, the camera is accessed by the terminal application running the server (e.g., Terminal, iTerm2). You must grant it camera permission before the app will work:

1. Open **System Settings** → **Privacy & Security** → **Camera**
2. Scroll down and enable the toggle for your terminal app (e.g., **Terminal** or **iTerm**)
3. If your terminal app does not appear in the list, try running `python3 app.py` first — macOS may prompt you automatically, or the app will appear in the list after the first access attempt
4. Restart your terminal after granting permission

## Getting Started

1. **Clone the repository:**
   ```bash
   git clone https://github.com/alextoddslick/PushupCounter.git
   cd PushupCounter
   ```

2. **Install dependencies:**
   It is recommended to use a virtual environment before installing the requirements.
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the application:**
   ```bash
   python3 app.py
   ```

4. **Access the application:**
   Open `http://localhost:5000` in your browser for the main interface.

## OBS Setup

1. In OBS, add a **Browser Source**.
2. Set the URL to `http://localhost:5001`.
3. Set width/height to fit your scene (e.g. 600×160).
4. Enable **"Shutdown source when not visible"** and check **"Refresh browser when scene becomes active"**.
5. The overlay background is fully transparent — no chroma key needed.

The overlay shows two panels side-by-side:
- **Left** — a live skeleton-only pose preview (no camera image, just the MediaPipe joint dots and connection lines on black).
- **Right** — the rep counter with a pulsing state badge (READY / HOLD).

## Usage

When you open the application in your browser:
- **Allow Camera Permission**: Your browser will ask for webcam access to detect your pose.
- **Select Camera**: Use the dropdown at the top right to choose an active webcam or continuity camera.
- **Stand in Frame**: Ensure your full body (or primarily upper body down to your legs) is visibly detectable by the tool. A confidence tracker will appear underneath the video feed.
- **Start Tracking**: Press **▶ Start** to begin counting reps.
- **Quick Adjust**: Use the `+` / `−` toggle and the **10 / 20 / 50** preset buttons to quickly correct the count without typing.
- **Tweak Settings**: Use the sidebar to enforce straight-leg checks, adjust horizontal limits, or change the rep detection thresholds per profile.

## Legal / Disclaimers

This software tool is designed for educational and fitness hobbyist exploration. Please perform workouts at your own risk and adapt your physical exercise in consultation with certified trainers or health providers.
