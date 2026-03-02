// ── State ───────────────────────────────────────────────────
let lastCount = 0;
let socket;
let audioCtx;
let quickMode = 'plus'; // 'plus' or 'minus'

// ── Ding Sound (Web Audio API) ──────────────────────────────
function playDing() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.type = 'sine';
    osc.frequency.setValueAtTime(880, audioCtx.currentTime);       // A5 note
    osc.frequency.setValueAtTime(1174.7, audioCtx.currentTime + 0.05); // D6 note
    gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.25);
    osc.start(audioCtx.currentTime);
    osc.stop(audioCtx.currentTime + 0.25);
}

// ── WebSocket Connection ────────────────────────────────────
function initSocket() {
    socket = io();

    socket.on('connect', () => {
        console.log('[WS] Connected');
        updateConnectionStatus(true);
    });

    socket.on('disconnect', () => {
        console.log('[WS] Disconnected');
        updateConnectionStatus(false);
    });

    socket.on('stats_update', (data) => {
        updateUI(data);
    });

    socket.on('camera_switched', (data) => {
        if (data.success) {
            // Reload the MJPEG stream
            const feed = document.getElementById('videoFeed');
            feed.src = '/video_feed?' + Date.now();
        }
    });
}

// ── UI Updates ──────────────────────────────────────────────
function updateUI(data) {
    // Count
    const countEl = document.getElementById('pushupCount');
    if (data.count !== lastCount) {
        countEl.textContent = data.count;
        countEl.classList.add('bump');
        setTimeout(() => countEl.classList.remove('bump'), 200);
        if (data.count > lastCount) playDing();
        lastCount = data.count;
    }

    // State
    const stateEl = document.getElementById('stateValue');
    stateEl.textContent = data.state;
    stateEl.className = 'stat-value ' + (data.state === 'UP' ? 'state-up' : 'state-down');

    // Time
    const seconds = Math.floor(data.elapsed_seconds);
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    document.getElementById('timeValue').textContent =
        `${mins}:${secs.toString().padStart(2, '0')}`;

    // Body detection
    const ring = document.getElementById('detectionRing');
    const title = document.getElementById('detectionTitle');
    const status = document.getElementById('detectionStatus');

    // Live Angles
    const elbowBox = document.getElementById('liveElbowBox');
    const elbowVal = document.getElementById('liveElbowVal');
    const legBox = document.getElementById('liveLegBox');
    const legVal = document.getElementById('liveLegVal');

    if (data.body_detected) {
        ring.classList.add('detected');
        title.textContent = 'Body Detected';
        status.textContent = 'Tracking active';

        // Update live angles
        if (data.elbow_angle !== undefined) {
            elbowVal.textContent = data.elbow_angle + '°';
            const targetAngle = data.state === 'UP' ? data.down_threshold : data.up_threshold;
            const op = data.state === 'UP' ? data.down_op : data.up_op;
            let good = false;
            if (op === 'le') good = data.elbow_angle <= targetAngle;
            else good = data.elbow_angle >= targetAngle;

            elbowBox.className = 'live-angle-box ' + (good ? 'good' : 'bad');
        }

        if (data.check_legs) {
            if (data.legs_visible) {
                legVal.textContent = data.leg_angle + '°';
                legBox.className = 'live-angle-box ' + (data.legs_straight ? 'good' : 'bad');
            } else {
                legVal.textContent = 'HIDE';
                legBox.className = 'live-angle-box warning';
            }
        } else {
            legVal.textContent = 'OFF';
            legBox.className = 'live-angle-box';
        }
    } else {
        ring.classList.remove('detected');
        title.textContent = 'No Body Found';
        status.textContent = 'Step into frame';

        // Clear live angles
        elbowVal.textContent = '—°';
        elbowBox.className = 'live-angle-box';
        legVal.textContent = '—°';
        legBox.className = 'live-angle-box';
    }

    // Feedback
    const feedbackText = data.form_feedback || 'Position yourself in front of the camera';
    document.getElementById('feedbackText').textContent = feedbackText;

    // Apply glow effect
    const feedbackCard = document.getElementById('feedbackCard');
    if (feedbackCard) {
        feedbackCard.className = 'feedback-card'; // reset classes
        const t = feedbackText.toLowerCase();

        if (t.includes('good') || t.includes('great') || t.includes('hold')) {
            feedbackCard.classList.add('glow-success');
        } else if (t.includes('counted') || t.includes('fast') || t.includes('straighten')) {
            feedbackCard.classList.add('glow-danger');
        } else if (t.includes('ready') || t.includes('steady') || t.includes('visibility') || t.includes('plank') || t.includes('step') || t.includes('get into')) {
            feedbackCard.classList.add('glow-warning');
        }
    }

    // Subtitle
    const subtitle = document.getElementById('counterSubtitle');
    if (data.count > 0) {
        const rate = data.elapsed_seconds > 0
            ? (data.count / (data.elapsed_seconds / 60)).toFixed(1)
            : '0';
        subtitle.textContent = `${rate} reps/min`;
    }

    // Speed & threshold indicators
    if (data.speed) {
        document.querySelectorAll('.speed-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.speed === data.speed);
        });
    }
    if (data.down_threshold !== undefined) {
        document.getElementById('downThreshold').textContent = data.down_threshold + '°';
        const el = document.getElementById('sliderDown');
        if (el && document.activeElement !== el) el.value = data.down_threshold;
        document.getElementById('sliderDownVal').textContent = data.down_threshold + '°';
    }
    if (data.up_threshold !== undefined) {
        document.getElementById('upThreshold').textContent = data.up_threshold + '°';
        const el = document.getElementById('sliderUp');
        if (el && document.activeElement !== el) el.value = data.up_threshold;
        document.getElementById('sliderUpVal').textContent = data.up_threshold + '°';
    }
    if (data.leg_threshold !== undefined) {
        const el = document.getElementById('sliderLeg');
        if (el && document.activeElement !== el) el.value = data.leg_threshold;
        document.getElementById('sliderLegVal').textContent = data.leg_threshold + '°';
    }

    // Cooldown & Confidence
    if (data.cooldown_time !== undefined) {
        const el = document.getElementById('sliderCooldown');
        if (el && document.activeElement !== el) el.value = data.cooldown_time;
        document.getElementById('sliderCooldownVal').textContent = data.cooldown_time + 's';
    }
    if (data.body_confidence !== undefined) {
        document.getElementById('confidenceVal').textContent = data.body_confidence;
        document.getElementById('confidenceDisplay').style.opacity = data.body_detected ? '1' : '0.3';
    } else {
        document.getElementById('confidenceVal').textContent = '—';
        document.getElementById('confidenceDisplay').style.opacity = '0.3';
    }

    // Leg check
    if (data.check_legs !== undefined) {
        document.getElementById('legCheckToggle').checked = data.check_legs;
    }
    if (data.leg_angle !== undefined && data.check_legs) {
        const legEl = document.getElementById('legAngleDisplay');
        legEl.textContent = `Leg angle: ${data.leg_angle}°`;
        legEl.className = 'leg-angle-display ' + (data.legs_straight ? 'good' : 'warning');
        document.getElementById('legSubtitle').textContent = data.legs_straight ? 'Legs look good ✓' : '⚠️ Bend detected';
    } else {
        document.getElementById('legAngleDisplay').textContent = '';
        document.getElementById('legSubtitle').textContent = 'Check form is correct';
    }

    // Horizontal check
    if (data.check_horizontal !== undefined) {
        document.getElementById('horizontalCheckToggle').checked = data.check_horizontal;
        document.getElementById('horizontalConfigGrp').style.opacity = data.check_horizontal ? '1' : '0.3';
        document.getElementById('horizontalConfigGrp').style.pointerEvents = data.check_horizontal ? 'auto' : 'none';
    }
    if (data.horiz_min !== undefined) {
        const el = document.getElementById('sliderHorizMin');
        if (el && document.activeElement !== el) el.value = data.horiz_min;
    }
    if (data.horiz_max !== undefined) {
        const el = document.getElementById('sliderHorizMax');
        if (el && document.activeElement !== el) el.value = data.horiz_max;
    }
    if (data.check_horizontal && data.body_detected && data.body_angle !== undefined) {
        document.getElementById('horizonContainer').style.opacity = '1';
        // 180 is perfectly horizontal
        const rot = data.body_angle - 180;
        document.getElementById('horizonBg').style.transform = `rotate(${rot}deg)`;

        document.getElementById('horizontalSubtitle').textContent = data.body_horizontal ? `Body is level ✓ (${data.body_angle}°)` : `⚠️ Angle too steep (${data.body_angle}°)`;
        document.getElementById('horizontalSubtitle').style.color = data.body_horizontal ? 'var(--success)' : 'var(--warning)';
    } else {
        document.getElementById('horizonContainer').style.opacity = '0.3';
        document.getElementById('horizonBg').style.transform = `rotate(0deg)`;

        document.getElementById('horizontalSubtitle').textContent = 'Ensure level pushup position';
        document.getElementById('horizontalSubtitle').style.color = 'var(--text-muted)';
    }

    // Running state
    if (data.running_state) {
        updatePlaybackButtons(data.running_state);
    }

    // Operator toggles
    if (data.down_op) document.getElementById('opDown').textContent = data.down_op === 'le' ? '≤' : '≥';
    if (data.up_op) document.getElementById('opUp').textContent = data.up_op === 'ge' ? '≥' : '≤';
    if (data.leg_op) document.getElementById('opLeg').textContent = data.leg_op === 'ge' ? '≥' : '≤';

    // Logs
    if (data.debug_logs) {
        updateDebugLogs(data.debug_logs);
    }
}

let currentLogsCount = 0;
function updateDebugLogs(logs) {
    const container = document.getElementById('debugLogsContainer');
    if (!container) return;

    if (logs.length === 0) {
        container.innerHTML = '<div class="debug-log-item">Waiting for pushups...</div>';
        currentLogsCount = 0;
        return;
    }

    // Only update if logs changed or first time
    if (logs.length !== currentLogsCount || container.children.length <= 1) {
        container.innerHTML = logs.map(msg => `<div class="debug-log-item">${msg}</div>`).join('');
        currentLogsCount = logs.length;
    }
}

function toggleDebug() {
    document.getElementById('debugWindow').classList.toggle('open');
}

function updateConnectionStatus(connected) {
    const dot = document.getElementById('statusDot');
    const text = document.getElementById('statusText');
    if (connected) {
        dot.classList.add('active');
        text.textContent = 'Connected';
    } else {
        dot.classList.remove('active');
        text.textContent = 'Reconnecting...';
    }
}

// ── Camera Selection ────────────────────────────────────────
async function loadCameras() {
    try {
        const res = await fetch('/cameras');
        const data = await res.json();
        const select = document.getElementById('cameraSelect');
        select.innerHTML = '';

        if (data.cameras.length === 0) {
            select.innerHTML = '<option value="-1">No cameras found</option>';
            return;
        }

        data.cameras.forEach(cam => {
            const opt = document.createElement('option');
            opt.value = cam.index;
            opt.textContent = `${cam.name} (${cam.resolution})`;
            if (cam.index === data.current) opt.selected = true;
            select.appendChild(opt);
        });

        select.addEventListener('change', (e) => {
            const idx = parseInt(e.target.value);
            if (idx >= 0) {
                socket.emit('switch_camera', { index: idx });
            }
        });
    } catch (err) {
        console.error('Failed to load cameras:', err);
    }
}

// ── Actions ─────────────────────────────────────────────────
function resetCounter() {
    socket.emit('reset_count');
    lastCount = 0;
    document.getElementById('pushupCount').textContent = '0';
    document.getElementById('counterSubtitle').textContent = 'Counter reset — go again!';
}

function adjustCount(delta) {
    socket.emit('adjust_count', { delta: delta });
}

function toggleQuickMode() {
    quickMode = quickMode === 'plus' ? 'minus' : 'plus';
    const btn = document.getElementById('quickModeToggle');
    const row = btn.closest('.quick-adjust-row');
    if (quickMode === 'minus') {
        btn.textContent = '−';
        btn.classList.add('minus-mode');
        row.classList.add('minus');
    } else {
        btn.textContent = '+';
        btn.classList.remove('minus-mode');
        row.classList.remove('minus');
    }
}

function quickAdjust(n) {
    adjustCount(quickMode === 'plus' ? n : -n);
}

function setCustomCount() {
    const input = document.getElementById('customCountInput');
    const value = parseInt(input.value);
    if (!isNaN(value) && value >= 0) {
        socket.emit('set_count', { value: value });
        input.value = '';
    }
}

function setSpeed(speed) {
    socket.emit('set_speed', { speed: speed });
    // Immediate visual feedback
    document.querySelectorAll('.speed-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.speed === speed);
    });
}

function setRunningState(state) {
    socket.emit('set_running_state', { state: state });
    updatePlaybackButtons(state);
}

function updatePlaybackButtons(state) {
    document.getElementById('startBtn').classList.toggle('active', state === 'running');
    document.getElementById('pauseBtn').classList.toggle('active', state === 'paused');
    document.getElementById('stopBtn').classList.toggle('active', state === 'stopped');
}

function toggleLegCheck(enabled) {
    socket.emit('toggle_leg_check', { enabled: enabled });
}

function toggleHorizontalCheck(enabled) {
    socket.emit('toggle_horizontal_check', { enabled: enabled });
}

function onSliderChange(sourceElem) {
    const down = document.getElementById('sliderDown').value;
    const up = document.getElementById('sliderUp').value;
    const leg = document.getElementById('sliderLeg').value;
    const cooldown = document.getElementById('sliderCooldown').value;

    // Make sure these are pulled properly
    let hMinStr = document.getElementById('sliderHorizMin').value;
    let hMaxStr = document.getElementById('sliderHorizMax').value;

    let hMinVal = parseInt(hMinStr) || 125;
    let hMaxVal = parseInt(hMaxStr) || 235;

    // Ensure min < max
    if (hMinVal > hMaxVal) {
        const temp = hMinVal;
        hMinVal = hMaxVal;
        hMaxVal = temp;
        document.getElementById('sliderHorizMin').value = hMinVal;
        document.getElementById('sliderHorizMax').value = hMaxVal;
    }

    document.getElementById('sliderDownVal').textContent = down + '°';
    document.getElementById('sliderUpVal').textContent = up + '°';
    document.getElementById('sliderLegVal').textContent = leg + '°';
    document.getElementById('sliderCooldownVal').textContent = cooldown + 's';

    document.getElementById('downThreshold').textContent = down + '°';
    document.getElementById('upThreshold').textContent = up + '°';
    document.querySelectorAll('.speed-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelector(`[data-profile="${window._currentProfile || 'profile1'}"]`)?.classList.add('active');

    const downOp = document.getElementById('opDown').textContent.trim() === '≤' ? 'le' : 'ge';
    const upOp = document.getElementById('opUp').textContent.trim() === '≥' ? 'ge' : 'le';
    const legOp = document.getElementById('opLeg').textContent.trim() === '≥' ? 'ge' : 'le';

    socket.emit('set_custom_thresholds', {
        down: parseInt(down), up: parseInt(up), leg: parseInt(leg),
        down_op: downOp, up_op: upOp, leg_op: legOp, cooldown: parseFloat(cooldown),
        horiz_min: parseInt(hMinVal), horiz_max: parseInt(hMaxVal)
    });
    updateRangeBars();

    const currentProfile = window._currentProfile || 'profile1';
    localStorage.setItem('pushup_' + currentProfile, JSON.stringify({
        down: parseInt(down), up: parseInt(up), leg: parseInt(leg),
        down_op: downOp, up_op: upOp, leg_op: legOp, cooldown: parseFloat(cooldown),
        horiz_min: parseInt(hMinVal), horiz_max: parseInt(hMaxVal)
    }));
}

const DEFAULT_PROFILE = {
    down: 80, up: 82, leg: 100, cooldown: 0.3,
    down_op: 'le', up_op: 'ge', leg_op: 'ge',
    horiz_min: 150, horiz_max: 210
};

function setProfile(profileId) {
    if (!profileId) return;
    window._currentProfile = profileId;

    // Update UI active state immediately
    document.querySelectorAll('.speed-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.profile === profileId);
    });

    const saved = localStorage.getItem('pushup_' + profileId);
    const v = saved ? JSON.parse(saved) : DEFAULT_PROFILE;

    if (document.getElementById('sliderDown')) document.getElementById('sliderDown').value = v.down;
    if (document.getElementById('sliderUp')) document.getElementById('sliderUp').value = v.up;
    if (document.getElementById('sliderLeg')) document.getElementById('sliderLeg').value = v.leg;
    if (v.cooldown !== undefined && document.getElementById('sliderCooldown')) document.getElementById('sliderCooldown').value = v.cooldown;
    if (v.horiz_min !== undefined && document.getElementById('sliderHorizMin')) document.getElementById('sliderHorizMin').value = v.horiz_min;
    if (v.horiz_max !== undefined && document.getElementById('sliderHorizMax')) document.getElementById('sliderHorizMax').value = v.horiz_max;

    if (document.getElementById('sliderDownVal')) document.getElementById('sliderDownVal').textContent = v.down + '°';
    if (document.getElementById('sliderUpVal')) document.getElementById('sliderUpVal').textContent = v.up + '°';
    if (document.getElementById('sliderLegVal')) document.getElementById('sliderLegVal').textContent = v.leg + '°';
    if (v.cooldown !== undefined && document.getElementById('sliderCooldownVal')) document.getElementById('sliderCooldownVal').textContent = v.cooldown + 's';

    if (document.getElementById('opDown')) document.getElementById('opDown').textContent = v.down_op === 'le' ? '≤' : '≥';
    if (document.getElementById('opUp')) document.getElementById('opUp').textContent = v.up_op === 'ge' ? '≥' : '≤';
    if (document.getElementById('opLeg')) document.getElementById('opLeg').textContent = v.leg_op === 'ge' ? '≥' : '≤';

    updateRangeBars();

    // Emit changes back to backend via existing custom payload
    onSliderChange();
}

function toggleProfileSettings(event, profileId) {
    if (event) event.stopPropagation(); // Don't trigger setProfile when clicking gear

    const panel = document.getElementById('profileSettingsPanel');
    const nameSpan = document.getElementById('settingsProfileName');

    if (!profileId || (panel.style.display === 'block' && window._settingsProfile === profileId)) {
        panel.style.display = 'none';
        window._settingsProfile = null;
    } else {
        window._settingsProfile = profileId;
        nameSpan.textContent = profileId.charAt(0).toUpperCase() + profileId.slice(1);
        panel.style.display = 'block';
        // Ensure values are correct for THIS profile being edited
        setProfile(profileId);
    }
}

function toggleOp(which) {
    const btn = document.getElementById('op' + which.charAt(0).toUpperCase() + which.slice(1));
    const current = btn.textContent.trim();
    btn.textContent = current === '≤' ? '≥' : '≤';
    onSliderChange();
}

function updateRangeBars() {
    const greenC = 'rgba(0, 221, 136, 0.5)';
    const redC = 'rgba(255, 68, 102, 0.35)';

    function paintBar(barId, value, minVal, maxVal, op) {
        const pct = ((value - minVal) / (maxVal - minVal)) * 100;
        const bar = document.getElementById(barId);
        const labels = bar.parentElement.querySelector('.range-labels');
        const leftLabel = labels.children[0];
        const rightLabel = labels.children[1];

        if (op === 'le') {
            // ≤: left = accepted (green), right = rejected (red)
            bar.style.background = `linear-gradient(to right, ${greenC} 0%, ${greenC} ${pct}%, ${redC} ${pct}%, ${redC} 100%)`;
            leftLabel.textContent = `✓ ${minVal}°`;
            leftLabel.style.color = '#00dd88';
            rightLabel.textContent = value + '°+';
            rightLabel.style.color = '#ff4466';
        } else {
            // ≥: left = rejected (red), right = accepted (green)
            bar.style.background = `linear-gradient(to right, ${redC} 0%, ${redC} ${pct}%, ${greenC} ${pct}%, ${greenC} 100%)`;
            leftLabel.textContent = `${minVal}°`;
            leftLabel.style.color = '#ff4466';
            rightLabel.textContent = value + '°+ ✓';
            rightLabel.style.color = '#00dd88';
        }
    }

    const downOp = document.getElementById('opDown').textContent.trim() === '≤' ? 'le' : 'ge';
    const upOp = document.getElementById('opUp').textContent.trim() === '≥' ? 'ge' : 'le';
    const legOp = document.getElementById('opLeg').textContent.trim() === '≥' ? 'ge' : 'le';

    paintBar('rangeBarDown', parseInt(document.getElementById('sliderDown').value), 0, 180, downOp);
    paintBar('rangeBarUp', parseInt(document.getElementById('sliderUp').value), 0, 180, upOp);
    paintBar('rangeBarLeg', parseInt(document.getElementById('sliderLeg').value), 60, 180, legOp);
}

// ── Video Error Handling ────────────────────────────────────
function setupVideoFeed() {
    const feed = document.getElementById('videoFeed');
    const placeholder = document.getElementById('videoPlaceholder');

    feed.onerror = () => {
        placeholder.style.display = 'flex';
        // Retry after a delay
        setTimeout(() => {
            feed.src = '/video_feed?' + Date.now();
        }, 2000);
    };

    feed.onload = () => {
        placeholder.style.display = 'none';
    };
}

// ── Init ────────────────────────────────────────────────────
async function checkCameraPermission() {
    try {
        const res = await fetch('/camera-permission');
        const data = await res.json();
        if (data.status === 'denied' || data.status === 'restricted') {
            document.getElementById('permissionBanner').style.display = 'flex';
        }
    } catch (_) {}
}

document.addEventListener('DOMContentLoaded', () => {
    initSocket();
    loadCameras();
    setupVideoFeed();
    setProfile('profile1');
    updateRangeBars();
    checkCameraPermission();

    document.getElementById('customCountInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') setCustomCount();
    });
});
