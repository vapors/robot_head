# behavior/reactions.py
import math
from behavior.state import EmotionalState

def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

def _lerp(a, b, t):
    return a + (b - a) * t

def _norm_conf(conf):
    """Normalize confidence to ~0..1 if it's 0..100 or already 0..1."""
    if not isinstance(conf, (int, float)):
        return None
    c = float(conf)
    if c > 1.5:
        c = c / 100.0
    return _clamp(c, 0.0, 1.0)

class BehaviorController:
    def __init__(self, face, body=None):
        self.face = face
        self.body = body

        self.emotion = EmotionalState()

        # IMU signals
        self.roll_deg = 0.0
        self.pitch_deg = 0.0
        self.tilt_deg = 0.0

        self.imu_stability = "Unknown"  # string
        self.imu_activity = None        # dict: {label, confidence, classes}

        # 0..1: how reactive we are (stable desk -> low; in motion -> high)
        self.imu_motion_gate = 0.3

        # Tick state
        self._breath_t = 0.0
        self._overlay_cooldowns = {
            "surprised": 0.0,
            "alert": 0.0,
            "sleepy": 0.0,
            "dizzy": 0.0,
        }

        # Proximity / social
        self.person_present = False
        self.person_distance_m = 99.0
        self.person_angle_deg = 0.0

        # Cache last base expression to reduce chatter
        self._last_base = None

    # ---------------- events ----------------
    def on_person_focus(self, data: dict):
        if not data.get("present"):
            self.person_present = False
            return

        self.person_present = True
        self.person_angle_deg = float(data.get("angle_deg", 0.0))
        self.person_distance_m = float(data.get("range_m", 99.0))

        d = self.person_distance_m
        if d < 1.0:
            self._set_base("happy")
            self.emotion.valence = _clamp(self.emotion.valence + 0.10, -1.0, 1.0)
            self.emotion.arousal = _clamp(self.emotion.arousal + 0.05, 0.0, 1.0)
        elif d < 2.0:
            self._set_base("curious")
            self.emotion.valence = _clamp(self.emotion.valence + 0.04, -1.0, 1.0)
            self.emotion.arousal = _clamp(self.emotion.arousal + 0.03, 0.0, 1.0)
        else:
            self._set_base("neutral")

    def on_imu_tilt(self, tilt: dict):
        if not tilt:
            return

        self.roll_deg = float(tilt.get("roll_deg", 0.0))
        self.pitch_deg = float(tilt.get("pitch_deg", 0.0))
        self.tilt_deg = float(tilt.get("tilt_deg", 0.0))

        stability = tilt.get("stability")
        activity = tilt.get("activity")

        if isinstance(stability, str) and stability:
            self.imu_stability = stability
        if isinstance(activity, dict) and activity.get("label"):
            self.imu_activity = activity

        # ---- stability -> motion gate ----
        st = self.imu_stability
        target_gate = 0.35

        if st in ("On Table", "Stable"):
            target_gate = 0.15
        elif st == "Stationary":
            target_gate = 0.25
        elif st == "In motion":
            target_gate = 1.0
        elif st == "Unknown":
            target_gate = 0.35

        # Smooth
        self.imu_motion_gate = _lerp(self.imu_motion_gate, target_gate, 0.15)

        # ---- activity influence (safe) ----
        label = None
        conf = None
        classes = None
        if self.imu_activity:
            label = self.imu_activity.get("label")
            conf = _norm_conf(self.imu_activity.get("confidence"))
            classes = self.imu_activity.get("classes")

        # If classes is a dict of probabilities, extract an extra vote (optional)
        # This lets the behavior respond even if "label" is noisy.
        classes_best = None
        classes_best_conf = None
        if isinstance(classes, dict) and classes:
            for k, v in classes.items():
                try:
                    vv = float(v)
                except Exception:
                    continue
                if classes_best_conf is None or vv > classes_best_conf:
                    classes_best = str(k)
                    classes_best_conf = vv
            if classes_best is not None and conf is None:
                # If we don't have a primary confidence, use the best class value
                conf = _clamp(float(classes_best_conf), 0.0, 1.0)

        act = label or classes_best
        conf_scale = conf if isinstance(conf, float) else 0.6  # safe default

        # Activity -> arousal style
        if act == "Still":
            self.emotion.arousal = _lerp(self.emotion.arousal, 0.12, 0.03 * conf_scale)
        elif act in ("Tilting", "On-Foot"):
            self.emotion.arousal = _clamp(self.emotion.arousal + 0.02 * conf_scale, 0.0, 1.0)
        elif act in ("Walking", "Running", "On Stairs"):
            self.emotion.arousal = _clamp(self.emotion.arousal + 0.06 * conf_scale, 0.0, 1.0)
            self._trigger_overlay("alert", 0.22 + 0.10 * conf_scale)
        elif act in ("In-Vehicle", "On-Bicycle"):
            self.emotion.valence = _clamp(self.emotion.valence - 0.02 * conf_scale, -1.0, 1.0)
            self.emotion.arousal = _clamp(self.emotion.arousal + 0.04 * conf_scale, 0.0, 1.0)

        # Main driver: arousal follows motion gate gently
        self.emotion.arousal = _lerp(self.emotion.arousal, self.imu_motion_gate, 0.08)

        # ---- micro pose (face-only for now) ----
        # Stronger when "in motion", quieter on table.
        micro_strength = 0.25 + 0.75 * self.imu_motion_gate
        self.face.set_head_pose(
            roll_deg=_clamp(self.roll_deg * 0.35 * micro_strength, -8.0, 8.0),
            pitch_deg=_clamp(self.pitch_deg * 0.35 * micro_strength, -8.0, 8.0),
        )

        # ---- big tilt reaction (rate-limited) ----
        if self.imu_motion_gate > 0.6 and self.tilt_deg > 18.0:
            self._trigger_overlay("surprised", 0.70)
            self.emotion.arousal = _clamp(self.emotion.arousal + 0.10, 0.0, 1.0)

    def on_imu_motion(self, motion: dict):
        if not motion:
            return
        if motion.get("shake", False):
            self._trigger_overlay("dizzy", 0.70)
            self.emotion.arousal = _clamp(self.emotion.arousal + 0.18, 0.0, 1.0)
            self.emotion.valence = _clamp(self.emotion.valence - 0.05, -1.0, 1.0)

    # ---------------- tick ----------------
    def update(self, dt: float):
        # Overlay cooldown timers
        for k in list(self._overlay_cooldowns.keys()):
            self._overlay_cooldowns[k] = max(0.0, self._overlay_cooldowns[k] - dt)

        # Baseline emotion drift
        self.emotion.decay_toward_baseline(dt)

        st = self.imu_stability
        if st in ("On Table", "Stable"):
            self.emotion.arousal = _lerp(self.emotion.arousal, 0.15, 0.02)
            self.emotion.valence = _lerp(self.emotion.valence, 0.10, 0.01)
        elif st == "In motion":
            self.emotion.arousal = _lerp(self.emotion.arousal, 0.65, 0.01)

        # Breathing (stronger when stable)
        self._breath_t += dt
        breath = 0.5 + 0.5 * math.sin(self._breath_t * 2.0 * math.pi * 0.18)  # ~5.5s
        breath_strength = 0.004 if st in ("On Table", "Stable") else 0.0015
        self.emotion.arousal = _clamp(self.emotion.arousal + (breath - 0.5) * breath_strength, 0.0, 1.0)

        # If no person present, set base expression from emotion bands
        if not self.person_present:
            self._apply_idle_expression_blend()
        else:
            # If a person is present, keep the base that proximity selected,
            # but allow subtle overlays from arousal.
            if self.emotion.arousal > 0.80:
                self._trigger_overlay("alert", 0.25)
            elif self.emotion.arousal < 0.14:
                self._trigger_overlay("sleepy", 0.18)

    # ---------------- internals ----------------
    def _set_base(self, name: str):
        if name != self._last_base:
            self.face.set_base_expression(name)
            self._last_base = name

    def _trigger_overlay(self, name: str, strength: float):
        # Simple rate limiting per overlay type
        if self._overlay_cooldowns.get(name, 0.0) > 0.0:
            return
        self.face.trigger_overlay(name, strength=float(strength))
        # Cooldown tuned per overlay
        if name == "surprised":
            self._overlay_cooldowns[name] = 0.9
        elif name == "dizzy":
            self._overlay_cooldowns[name] = 1.2
        elif name in ("alert", "sleepy"):
            self._overlay_cooldowns[name] = 0.6
        else:
            self._overlay_cooldowns[name] = 0.7

    def _apply_idle_expression_blend(self):
        # Base expression from valence
        if self.emotion.valence > 0.25:
            self._set_base("content")
        elif self.emotion.valence < -0.25:
            self._set_base("worried")
        else:
            self._set_base("neutral")

        # Subtle overlays from arousal
        if self.emotion.arousal > 0.82:
            self._trigger_overlay("alert", 0.30)
        elif self.emotion.arousal < 0.16:
            self._trigger_overlay("sleepy", 0.22)
