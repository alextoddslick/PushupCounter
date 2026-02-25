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

## Prerequisites

Before getting started, make sure you have the following installed on your system:
- Python 3.8+
- [pip](https://pip.pypa.io/en/stable/installation/)

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
   *(If `requirements.txt` is not present, you will need minimum packages: `flask`, `flask-socketio`, `opencv-python`, `mediapipe`, and `numpy`).*

3. **Start the application:**
   You can run the web server by executing the main script:
   ```bash
   python3 app.py
   ```

4. **Access the application:**
   Once the server starts running, open your web browser and navigate to the local address provided (typically `http://localhost:5000` or `http://127.0.0.1:5000`).

## Usage

When you open the application in your browser:
- **Allow Camera Permission**: Your browser will ask for webcam access to detect your pose.
- **Select Camera**: Use the dropdown at the top right to choose an active webcam or continuity camera.
- **Stand in Frame**: Ensure your full body (or primarily upper body down to your legs) is visibly detectable by the tool. A confidence tracker will appear underneath the video feed.
- **Tweak Settings**: You can use the sidebar to enforce straight legs toggles, adjust horizontal limits, or change the rep detection speeds.

## Legal / Disclaimers
This software tool is designed for educational and fitness hobbyist exploration. Please perform workouts at your own risk and adapt your physical exercise in consultation with certified trainers or health providers.
