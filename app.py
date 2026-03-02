"""
Pushup Counter — MediaPipe + Flask Backend
Uses OpenCV to capture video (supports macOS Continuity Camera / iPhone),
MediaPipe Pose to detect body landmarks, and counts pushups via elbow angle.
Streams annotated video as MJPEG and pushup stats via WebSocket.
"""

import cv2
import numpy as np
import mediapipe as mp
import math
import time
import threading
import platform
from flask import Flask, render_template, Response, jsonify, request, send_file
from flask_socketio import SocketIO, emit
import os
import secrets

# ═══════════════════════════════════════════════════════════════════════════════
# macOS Camera Permission
# ═══════════════════════════════════════════════════════════════════════════════
def _get_av_capture_device():
    """Load AVCaptureDevice class via pyobjc (macOS only)."""
    try:
        import objc
        from Foundation import NSBundle
        bundle = NSBundle.bundleWithPath_(
            '/System/Library/Frameworks/AVFoundation.framework'
        )
        bundle.load()
        return objc.lookUpClass('AVCaptureDevice')
    except Exception:
        return None


def get_camera_permission_status():
    """Return 'authorized', 'denied', 'not_determined', or 'unavailable'."""
    if platform.system() != 'Darwin':
        return 'authorized'
    cls = _get_av_capture_device()
    if cls is None:
        return 'unavailable'
    code = cls.authorizationStatusForMediaType_('vide')
    return {0: 'not_determined', 1: 'restricted', 2: 'denied', 3: 'authorized'}.get(code, 'unavailable')


def request_camera_permission():
    """Trigger the macOS camera permission dialog if needed. Returns True if granted."""
    if platform.system() != 'Darwin':
        return True
    status = get_camera_permission_status()
    if status == 'authorized':
        return True
    if status == 'not_determined':
        cls = _get_av_capture_device()
        if cls is None:
            return True
        done = threading.Event()
        result = [False]

        def handler(granted):
            result[0] = bool(granted)
            done.set()

        cls.requestAccessForMediaType_completionHandler_('vide', handler)
        done.wait(timeout=30)
        if result[0]:
            print("[Camera] Permission granted ✅")
        else:
            print("[Camera] Permission denied ❌")
        return result[0]
    # denied or restricted
    print(f"[Camera] Permission status: {status} — user must enable in System Settings")
    return False


# ─── App Setup ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(16))
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# ─── MediaPipe Setup ────────────────────────────────────────────────────────────
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles

# ─── Global State ───────────────────────────────────────────────────────────────
camera_lock = threading.Lock()
current_camera_index = 0
cap = None


# ═══════════════════════════════════════════════════════════════════════════════
# Pushup Detector
# ═══════════════════════════════════════════════════════════════════════════════
class PushupDetector:
    """Detects and counts pushups using MediaPipe Pose landmarks."""

    def __init__(self):
        self.pose = mp_pose.Pose(
            static_image_mode=False,
            model_complexity=0,      # fastest model for high-speed tracking
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.3,  # lower = faster re-acquisition
        )
        self.count = 0
        self.state = "UP"  # UP or DOWN
        self.form_feedback = "Get into pushup position"
        self.elbow_angle = 0
        self.leg_angle = 0
        self.legs_straight = True
        self.check_legs = True   # on by default
        self.check_horizontal = True # horizontal body check on by default
        self.body_horizontal = False
        self.horiz_min = 150
        self.horiz_max = 210
        self.leg_threshold = 100
        self.down_op = "le"
        self.up_op = "ge"
        self.leg_op = "ge"
        self.body_detected = False
        self.start_time = None
        self.landmarks_data = None
        self.running_state = "stopped"  # stopped, running, paused
        
        # Speed limiter
        self.cooldown_time = 0.3
        self.last_rep_time = 0.0
        
        self.body_confidence = 0.0
        
        # Default initialization mimicking the base profile
        self.DOWN_ANGLE = 80
        self.UP_ANGLE = 82

    def _calculate_angle(self, a, b, c):
        """Calculate the angle at point b formed by points a, b, c."""
        a = np.array([a.x, a.y])
        b_pt = np.array([b.x, b.y])
        c = np.array([c.x, c.y])

        ba = a - b_pt
        bc = c - b_pt

        cosine = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
        cosine = np.clip(cosine, -1.0, 1.0)
        angle = math.degrees(math.acos(cosine))
        return angle

    def _calculate_horizontal_angle(self, left_shoulder, right_shoulder, left_hip, right_hip):
        """Calculate the angle of the torso relative to the horizontal (0 degrees)."""
        # Average shoulder and hip positions
        shoulder_x = (left_shoulder.x + right_shoulder.x) / 2
        shoulder_y = (left_shoulder.y + right_shoulder.y) / 2
        hip_x = (left_hip.x + right_hip.x) / 2
        hip_y = (left_hip.y + right_hip.y) / 2

        dx = shoulder_x - hip_x
        dy = shoulder_y - hip_y
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return 180.0

        # dy < 0 means shoulders are higher than hips (incline)
        # dy > 0 means shoulders are lower than hips (decline)
        angle_offset = math.degrees(math.asin(dy / dist))
        return 180.0 + angle_offset

    def _check_body_alignment(self, landmarks):
        """Check if the body is roughly horizontal (pushup position)."""
        left_shoulder = landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value]
        left_hip = landmarks[mp_pose.PoseLandmark.LEFT_HIP.value]
        right_shoulder = landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
        right_hip = landmarks[mp_pose.PoseLandmark.RIGHT_HIP.value]

        # Calculate actual body angle relative to horizontal plane
        self.body_angle = self._calculate_horizontal_angle(
            left_shoulder, right_shoulder, left_hip, right_hip
        )

        # Check against target bounding thresholds
        self.body_horizontal = self.horiz_min <= self.body_angle <= self.horiz_max
            
        if self.check_horizontal:
            return self.body_horizontal and self.body_confidence >= 0.80
        return True

    def process_frame(self, frame):
        """Process a frame and return annotated image + stats."""
        # If not running, return raw frame (save CPU)
        if self.running_state != "running":
            return frame

        if self.start_time is None:
            self.start_time = time.time()

        # Convert BGR to RGB for MediaPipe
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False
        results = self.pose.process(rgb_frame)
        rgb_frame.flags.writeable = True

        annotated = frame.copy()

        if results.pose_landmarks:
            landmarks = results.pose_landmarks.landmark
            
            # Check visibility of core torso landmarks (shoulders and hips)
            # This prevents MediaPipe from hallucinating bodies on blankets/pillows
            core_indices = [
                mp_pose.PoseLandmark.LEFT_SHOULDER.value,
                mp_pose.PoseLandmark.RIGHT_SHOULDER.value,
                mp_pose.PoseLandmark.LEFT_HIP.value,
                mp_pose.PoseLandmark.RIGHT_HIP.value
            ]
            
            # Average visibility of the torso
            avg_vis = sum(landmarks[idx].visibility for idx in core_indices) / len(core_indices)
            self.body_confidence = avg_vis
            
            # Only count as a body if the torso is reasonably visible
            if avg_vis > 0.6:
                self.body_detected = True
                self.landmarks_data = results.pose_landmarks
            else:
                self.body_detected = False
                self.landmarks_data = None
        else:
            self.body_confidence = 0.0
                
        if self.body_detected and self.landmarks_data:
            landmarks = self.landmarks_data.landmark

            # Calculate elbow angles for both arms
            left_angle = self._calculate_angle(
                landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value],
                landmarks[mp_pose.PoseLandmark.LEFT_ELBOW.value],
                landmarks[mp_pose.PoseLandmark.LEFT_WRIST.value],
            )
            right_angle = self._calculate_angle(
                landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER.value],
                landmarks[mp_pose.PoseLandmark.RIGHT_ELBOW.value],
                landmarks[mp_pose.PoseLandmark.RIGHT_WRIST.value],
            )

            # Use average of both arms (more robust)
            self.elbow_angle = (left_angle + right_angle) / 2

            # Leg straightness check (hip → knee → ankle)
            l_hip = landmarks[mp_pose.PoseLandmark.LEFT_HIP.value]
            l_knee = landmarks[mp_pose.PoseLandmark.LEFT_KNEE.value]
            l_ankle = landmarks[mp_pose.PoseLandmark.LEFT_ANKLE.value]
            r_hip = landmarks[mp_pose.PoseLandmark.RIGHT_HIP.value]
            r_knee = landmarks[mp_pose.PoseLandmark.RIGHT_KNEE.value]
            r_ankle = landmarks[mp_pose.PoseLandmark.RIGHT_ANKLE.value]

            l_vis = l_hip.visibility > 0.5 and l_knee.visibility > 0.5 and l_ankle.visibility > 0.5
            r_vis = r_hip.visibility > 0.5 and r_knee.visibility > 0.5 and r_ankle.visibility > 0.5

            self.legs_visible = l_vis or r_vis

            if self.legs_visible:
                left_leg = self._calculate_angle(l_hip, l_knee, l_ankle) if l_vis else 0
                right_leg = self._calculate_angle(r_hip, r_knee, r_ankle) if r_vis else 0

                if l_vis and r_vis:
                    self.leg_angle = (left_leg + right_leg) / 2
                elif l_vis:
                    self.leg_angle = left_leg
                else:
                    self.leg_angle = right_leg

                self.legs_straight = (self.leg_angle >= self.leg_threshold) if self.leg_op == "ge" else (self.leg_angle <= self.leg_threshold)
            else:
                self.leg_angle = None
                self.legs_straight = True  # Don't penalize if we can't see them

            # Check body alignment
            in_position = self._check_body_alignment(landmarks)

            # Leg form warning (if enabled)
            leg_warning = ""
            legs_ok = True
            if self.check_legs:
                if not self.legs_visible:
                    leg_warning = " ⚠️ Legs out of frame!"
                    legs_ok = False
                elif not self.legs_straight:
                    leg_warning = " ⚠️ Straighten your legs!"
                    legs_ok = False

            if in_position:
                # Compare using configurable operators
                down_met = (self.elbow_angle <= self.DOWN_ANGLE) if self.down_op == "le" else (self.elbow_angle >= self.DOWN_ANGLE)
                up_met = (self.elbow_angle >= self.UP_ANGLE) if self.up_op == "ge" else (self.elbow_angle <= self.UP_ANGLE)

                # State machine for pushup counting
                if down_met and self.state == "UP":
                    if legs_ok:
                        self.state = "DOWN"
                        self.down_trigger_elbow = self.elbow_angle
                        self.down_trigger_leg = self.leg_angle
                        self.form_feedback = "Good depth! Now push up!" + leg_warning
                    else:
                        self.form_feedback = "Straighten your legs before going down!"
                elif up_met and self.state == "DOWN":
                    current_time = time.time()
                    time_since_last = current_time - self.last_rep_time
                    
                    if not legs_ok:
                        self.form_feedback = "Rep not counted — straighten your legs!"
                    elif time_since_last < self.cooldown_time:
                        self.form_feedback = f"Rep not counted — too fast! (Wait {self.cooldown_time}s)"
                        
                        # Generate debug log for rejected rep
                        if not hasattr(self, "debug_logs"): self.debug_logs = []
                        log_msg = f"❌ Rep REJECTED (Speed) | Time since last: {time_since_last:.2f}s (req ≥{self.cooldown_time}s)"
                        self.debug_logs.insert(0, log_msg)
                        if len(self.debug_logs) > 50: self.debug_logs.pop()
                    else:
                        self.state = "UP"
                        self.count += 1
                        self.last_rep_time = current_time
                        
                        # Generate debug log
                        op_d = "≤" if self.down_op == "le" else "≥"
                        op_u = "≤" if self.up_op == "le" else "≥"
                        op_l = "≤" if self.leg_op == "le" else "≥"
                        
                        d_elb = f"{self.down_trigger_elbow:.1f}°" if hasattr(self, "down_trigger_elbow") else "?"
                        d_leg = f"{self.down_trigger_leg:.1f}°" if hasattr(self, "down_trigger_leg") and self.down_trigger_leg is not None else "N/A"
                        u_elb = f"{self.elbow_angle:.1f}°"
                        u_leg = f"{self.leg_angle:.1f}°" if self.leg_angle is not None else "N/A"
                        
                        if not hasattr(self, "debug_logs"): self.debug_logs = []
                        log_msg = f"Rep {self.count} | DOWN: Elbow {d_elb} (req {op_d}{self.DOWN_ANGLE}°), Leg {d_leg} (req {op_l}{self.leg_threshold}°) | UP: Elbow {u_elb} (req {op_u}{self.UP_ANGLE}°), Leg {u_leg}"
                        self.debug_logs.insert(0, log_msg)
                        if len(self.debug_logs) > 50: self.debug_logs.pop()

                        self.form_feedback = f"Great rep! Keep going!" + leg_warning
                elif self.state == "DOWN":
                    self.form_feedback = "Hold... now push up!" + leg_warning
                elif self.state == "UP" and up_met:
                    self.form_feedback = "Ready — go down!" + leg_warning
                else:
                    self.form_feedback = "Keep your form steady" + leg_warning
            else:
                if self.check_horizontal and self.body_confidence < 0.80:
                    self.form_feedback = f"Low body visibility ({int(self.body_confidence * 100)}%). Need 80%+ to count."
                else:
                    self.form_feedback = "Align your body — get into plank position"

            # Draw skeleton with custom styling
            self._draw_skeleton(annotated, results.pose_landmarks)

            # Draw unmet criteria overlays
            self._draw_unmet_criteria(annotated, landmarks)
        else:
            self.body_detected = False
            self.form_feedback = "No body detected — step into frame"

        # Draw HUD overlay
        self._draw_hud(annotated)

        return annotated

    def _draw_skeleton(self, frame, pose_landmarks):
        """Draw the pose skeleton with custom colors."""
        # Custom drawing spec for landmarks
        landmark_spec = mp_drawing.DrawingSpec(
            color=(0, 255, 200), thickness=3, circle_radius=4
        )
        connection_spec = mp_drawing.DrawingSpec(
            color=(0, 200, 255), thickness=2, circle_radius=2
        )

        mp_drawing.draw_landmarks(
            frame,
            pose_landmarks,
            mp_pose.POSE_CONNECTIONS,
            landmark_drawing_spec=landmark_spec,
            connection_drawing_spec=connection_spec,
        )

    def _draw_unmet_criteria(self, frame, landmarks):
        """Draw angle indicators only for criteria that are currently failing."""
        h, w, _ = frame.shape
        
        def draw_angle_pill(x, y, angle_val, color=(0, 0, 255)):
            text = f"{int(angle_val)}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(frame, (x - tw // 2 - 6, y - th - 8), (x + tw // 2 + 6, y + 6), (0, 0, 0), -1)
            cv2.rectangle(frame, (x - tw // 2 - 6, y - th - 8), (x + tw // 2 + 6, y + 6), color, 1)
            cv2.putText(frame, text, (x - tw // 2, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # 1. Elbows (Target depends on current UP/DOWN state)
        elbow_ok = True
        if self.state == "UP":
            elbow_ok = (self.elbow_angle <= self.DOWN_ANGLE) if self.down_op == "le" else (self.elbow_angle >= self.DOWN_ANGLE)
        elif self.state == "DOWN":
            elbow_ok = (self.elbow_angle >= self.UP_ANGLE) if self.up_op == "ge" else (self.elbow_angle <= self.UP_ANGLE)
            
        if not elbow_ok:
            for side, elbow_idx in [("L", mp_pose.PoseLandmark.LEFT_ELBOW.value), ("R", mp_pose.PoseLandmark.RIGHT_ELBOW.value)]:
                elbow = landmarks[elbow_idx]
                if elbow.visibility > 0.5:
                    x, y = int(elbow.x * w), int(elbow.y * h)
                    angle = self._calculate_angle(landmarks[elbow_idx - 2], landmarks[elbow_idx], landmarks[elbow_idx + 2])
                    draw_angle_pill(x, y, angle, (0, 0, 255)) # Red for unmet elbow target
                    
        # 2. Legs (Must be straight)
        if self.check_legs and getattr(self, "legs_visible", False) and not getattr(self, "legs_straight", True):
            for side, knee_idx in [("L", mp_pose.PoseLandmark.LEFT_KNEE.value), ("R", mp_pose.PoseLandmark.RIGHT_KNEE.value)]:
                knee = landmarks[knee_idx]
                if knee.visibility > 0.5:
                    x, y = int(knee.x * w), int(knee.y * h)
                    angle = self._calculate_angle(landmarks[knee_idx - 2], landmarks[knee_idx], landmarks[knee_idx + 2])
                    draw_angle_pill(x, y, angle, (0, 165, 255)) # Orange for unmet leg straightness
                    
        # 3. Horizontal Body (Must be within tolerance of target plane)
        if self.check_horizontal and getattr(self, "body_detected", False) and not getattr(self, "body_horizontal", True):
            l_hip = landmarks[mp_pose.PoseLandmark.LEFT_HIP.value]
            r_hip = landmarks[mp_pose.PoseLandmark.RIGHT_HIP.value]
            if getattr(self, "body_angle", None) is not None:
                x = int((l_hip.x + r_hip.x) / 2 * w)
                y = int((l_hip.y + r_hip.y) / 2 * h)
                draw_angle_pill(x, y, self.body_angle, (255, 0, 255)) # Magenta for unmet horizontal pitch

    def _draw_hud(self, frame):
        """Draw a minimal heads-up display on the video frame."""
        h, w, _ = frame.shape

        # State indicator (top-left)
        state_color = (0, 200, 100) if self.state == "UP" else (0, 100, 255)
        cv2.putText(
            frame, f"State: {self.state}",
            (15, 35),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, state_color, 2,
        )

        # Count (top-left, below state)
        cv2.putText(
            frame, f"Reps: {self.count}",
            (15, 70),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2,
        )

        # Target indicator (top-left, below count)
        op_d_str = "<=" if self.down_op == "le" else ">="
        op_u_str = "<=" if self.up_op == "le" else ">="
        if self.state == "UP":
            target_text = f"Target: Bend arms {op_d_str} {self.DOWN_ANGLE} deg"
        else:
            target_text = f"Target: Straighten arms {op_u_str} {self.UP_ANGLE} deg"
            
        cv2.putText(
            frame, target_text,
            (15, 105),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2,
        )

    def get_stats(self):
        """Return current stats dictionary."""
        elapsed = time.time() - self.start_time if self.start_time else 0
        return {
            "count": self.count,
            "state": self.state,
            "elbow_angle": round(self.elbow_angle, 1),
            "leg_angle": round(self.leg_angle, 1) if self.leg_angle is not None else None,
            "legs_straight": self.legs_straight,
            "legs_visible": getattr(self, "legs_visible", False),
            "check_legs": self.check_legs,
            "form_feedback": self.form_feedback,
            "body_detected": self.body_detected,
            "check_horizontal": self.check_horizontal,
            "body_horizontal": getattr(self, "body_horizontal", False),
            "body_angle": round(getattr(self, "body_angle", 0), 1),
            "horiz_min": getattr(self, "horiz_min", 150),
            "horiz_max": getattr(self, "horiz_max", 210),
            "elapsed_seconds": round(elapsed, 1),
            "down_threshold": self.DOWN_ANGLE,
            "up_threshold": self.UP_ANGLE,
            "leg_threshold": self.leg_threshold,
            "cooldown_time": self.cooldown_time,
            "down_op": self.down_op,
            "up_op": self.up_op,
            "leg_op": self.leg_op,
            "debug_logs": getattr(self, "debug_logs", []),
            "running_state": self.running_state,
            "body_confidence": int(self.body_confidence * 100) if hasattr(self, "body_confidence") else 0,
        }

    def reset(self):
        """Reset the counter."""
        self.count = 0
        self.state = "UP"
        self.start_time = None
        self.running_state = "stopped"
        self.form_feedback = "Counter reset — get ready!"


# ─── Global Detector ────────────────────────────────────────────────────────────
detector = PushupDetector()


# ═══════════════════════════════════════════════════════════════════════════════
# Camera Management
# ═══════════════════════════════════════════════════════════════════════════════
def get_available_cameras(max_cameras=5):
    """Enumerate available cameras on the system."""
    cameras = []
    for i in range(max_cameras):
        test_cap = cv2.VideoCapture(i)
        if test_cap.isOpened():
            w = int(test_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(test_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cameras.append({
                "index": i,
                "name": f"Camera {i}",
                "resolution": f"{w}x{h}",
            })
            test_cap.release()
    return cameras


def init_camera(index=0):
    """Initialize camera capture with the given index."""
    global cap, current_camera_index
    with camera_lock:
        if cap is not None:
            cap.release()
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            # Set reasonable resolution
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            cap.set(cv2.CAP_PROP_FPS, 30)
            current_camera_index = index
            return True
        return False


def generate_frames():
    """Generator that yields MJPEG frames with pose overlay."""
    global cap
    frame_count = 0

    while True:
        with camera_lock:
            if cap is None or not cap.isOpened():
                # Yield a blank frame
                blank = np.zeros((720, 1280, 3), dtype=np.uint8)
                cv2.putText(
                    blank, "No camera connected",
                    (400, 360), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (100, 100, 100), 2,
                )
                _, buffer = cv2.imencode(".jpg", blank)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + buffer.tobytes()
                    + b"\r\n"
                )
                eventlet_sleep(0.1)
                continue

            success, frame = cap.read()

        if not success:
            eventlet_sleep(0.01)
            continue

        # Process with MediaPipe
        annotated = detector.process_frame(frame)

        # Encode to JPEG
        _, buffer = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + buffer.tobytes()
            + b"\r\n"
        )

        # Emit stats via WebSocket every 3 frames
        frame_count += 1
        if frame_count % 3 == 0:
            socketio.emit("stats_update", detector.get_stats())

        eventlet_sleep(0.01)


def generate_pose_frames():
    """Generator that yields MJPEG frames with only the skeleton on a black background."""
    global cap

    while True:
        with camera_lock:
            if cap is None or not cap.isOpened():
                blank = np.zeros((720, 1280, 3), dtype=np.uint8)
                _, buffer = cv2.imencode(".jpg", blank)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + buffer.tobytes()
                    + b"\r\n"
                )
                eventlet_sleep(0.1)
                continue

            success, frame = cap.read()

        if not success:
            eventlet_sleep(0.01)
            continue

        # Run MediaPipe on the real frame so landmarks are up-to-date,
        # but draw only the skeleton onto a pure-black canvas.
        h, w = frame.shape[:2]
        black = np.zeros((h, w, 3), dtype=np.uint8)

        if detector.running_state == "running" and detector.landmarks_data is not None:
            detector._draw_skeleton(black, detector.landmarks_data)
            detector._draw_unmet_criteria(black, detector.landmarks_data.landmark)

        _, buffer = cv2.imencode(".jpg", black, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + buffer.tobytes()
            + b"\r\n"
        )

        eventlet_sleep(0.01)


def eventlet_sleep(seconds):
    """Sleep that works with eventlet."""
    try:
        import eventlet
        eventlet.sleep(seconds)
    except ImportError:
        time.sleep(seconds)


# ═══════════════════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    """Serve the main HTML page."""
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    """MJPEG video stream endpoint."""
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/pose_feed")
def pose_feed():
    """MJPEG stream — skeleton only on black background."""
    return Response(
        generate_pose_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/cameras")
def list_cameras():
    """List available cameras."""
    cameras = get_available_cameras()
    return jsonify({"cameras": cameras, "current": current_camera_index})


@app.route("/stats")
def get_stats():
    """Get current pushup stats (REST fallback)."""
    return jsonify(detector.get_stats())


@app.route("/camera-permission")
def camera_permission():
    """Return current macOS camera permission status."""
    return jsonify({"status": get_camera_permission_status()})


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket Events
# ═══════════════════════════════════════════════════════════════════════════════
@socketio.on("connect")
def handle_connect():
    """Handle new WebSocket connection."""
    emit("stats_update", detector.get_stats())
    print("[WS] Client connected")


@socketio.on("switch_camera")
def handle_switch_camera(data):
    """Switch to a different camera."""
    index = data.get("index", 0)
    success = init_camera(index)
    emit("camera_switched", {"success": success, "index": index})
    print(f"[WS] Camera switched to index {index}: {'OK' if success else 'FAIL'}")


@socketio.on("reset_count")
def handle_reset():
    """Reset the pushup counter."""
    detector.reset()
    emit("stats_update", detector.get_stats())
    print("[WS] Counter reset")


@socketio.on("adjust_count")
def handle_adjust_count(data):
    """Manually increment or decrement the pushup count."""
    delta = int(data.get("delta", 0))
    detector.count = max(0, detector.count + delta)
    emit("stats_update", detector.get_stats())
    print(f"[WS] Count adjusted by {delta:+d} → {detector.count}")


@socketio.on("set_count")
def handle_set_count(data):
    """Manually set the pushup count to a specific value."""
    value = int(data.get("value", 0))
    detector.count = max(0, value)
    emit("stats_update", detector.get_stats())
    print(f"[WS] Count set to {detector.count}")



@socketio.on("set_running_state")
def handle_running_state(data):
    """Start, pause, or stop the detector."""
    state = data.get("state", "stopped")
    if state in ("running", "paused", "stopped"):
        detector.running_state = state
        if state == "stopped":
            detector.start_time = None
        emit("stats_update", detector.get_stats())
        print(f"[WS] Running state: {state}")


@socketio.on("toggle_leg_check")
def handle_toggle_leg_check(data):
    """Toggle leg straightness checking."""
    detector.check_legs = data.get("enabled", False)
    emit("stats_update", detector.get_stats())
    print(f"[WS] Leg check: {'ON' if detector.check_legs else 'OFF'}")


@socketio.on("toggle_horizontal_check")
def handle_toggle_horizontal_check(data):
    """Toggle horizontal alignment checking."""
    detector.check_horizontal = data.get("enabled", False)
    emit("stats_update", detector.get_stats())
    print(f"[WS] Horizontal check: {'ON' if detector.check_horizontal else 'OFF'}")


@socketio.on("set_custom_thresholds")
def handle_custom_thresholds(data):
    """Set custom angle thresholds and operators."""
    if "down" in data:
        detector.DOWN_ANGLE = int(data["down"])
    if "up" in data:
        detector.UP_ANGLE = int(data["up"])
    if "leg" in data:
        detector.leg_threshold = int(data["leg"])
    if "down_op" in data and data["down_op"] in ("le", "ge"):
        detector.down_op = data["down_op"]
    if "up_op" in data and data["up_op"] in ("le", "ge"):
        detector.up_op = data["up_op"]
    if "leg_op" in data and data["leg_op"] in ("le", "ge"):
        detector.leg_op = data["leg_op"]
    if "cooldown" in data:
        detector.cooldown_time = float(data["cooldown"])
    if "horiz_min" in data:
        detector.horiz_min = int(data["horiz_min"])
    if "horiz_max" in data:
        detector.horiz_max = int(data["horiz_max"])

    emit("stats_update", detector.get_stats())
    print(f"[WS] Custom: down={detector.DOWN_ANGLE}({detector.down_op}), up={detector.UP_ANGLE}({detector.up_op}), leg={detector.leg_threshold}({detector.leg_op}), cooldown={detector.cooldown_time}s, horiz_range={detector.horiz_min}°-{detector.horiz_max}°")

# ═══════════════════════════════════════════════════════════════════════════════
# OBS App Setup
# ═══════════════════════════════════════════════════════════════════════════════
obs_app = Flask("obs_counter")

@obs_app.route("/")
def obs_index():
    return render_template("obs.html")

def run_obs_server():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    obs_app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)

# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  PUSHUP COUNTER — MediaPipe + Flask")
    print("=" * 60)

    # Start OBS server thread
    obs_thread = threading.Thread(target=run_obs_server, daemon=True)
    obs_thread.start()

    # Request camera permission (macOS: triggers system dialog if needed)
    print("\n🔐  Checking camera permissions...")
    permission_granted = request_camera_permission()
    if not permission_granted:
        print("⚠️   Camera permission denied. Enable it in System Settings → Privacy & Security → Camera")

    # List available cameras
    cameras = get_available_cameras()
    print(f"\n📷  Found {len(cameras)} camera(s):")
    for cam in cameras:
        print(f"   [{cam['index']}] {cam['name']} — {cam['resolution']}")

    # Initialize the first available camera
    if cameras:
        init_camera(cameras[0]["index"])
        print(f"\n✅  Using camera index {cameras[0]['index']}")
    else:
        print("\n⚠️   No cameras found! Connect a camera and restart.")

    print(f"\n🌐  Open http://localhost:5000 in your browser")
    print(f"🎥  OBS Source URL: http://localhost:5001")
    print("=" * 60)

    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
