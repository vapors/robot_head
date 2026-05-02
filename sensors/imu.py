# sensors/imu.py
import time
import math
import board
import busio
import adafruit_bno08x
from adafruit_bno08x.i2c import BNO08X_I2C

def _try_enable(bno, feature):
    if feature is None:
        return False
    try:
        bno.enable_feature(feature)
        return True
    except Exception as e:
        print(f"[IMU] warn: couldn't enable feature {feature!r}: {e}")
        return False

def _safe_read(getter, default=None):
    try:
        return getter()
    except Exception:
        return default

def _tilt_from_gravity(gx, gy, gz):
    roll = math.degrees(math.atan2(gy, gz))
    pitch = math.degrees(math.atan2(-gx, math.sqrt(gy * gy + gz * gz)))
    tilt_mag = math.sqrt(roll * roll + pitch * pitch)
    return roll, pitch, tilt_mag

def _pick_activity_label(activity):
    """Normalize activity classification into:
       {"label": str, "confidence": float|None, "classes": dict|None}
    """
    if activity is None:
        return None

    # Some versions return a string directly
    if isinstance(activity, str):
        return {"label": activity, "confidence": None, "classes": None}

    if isinstance(activity, dict) and activity:
        # Common shapes:
        # 1) {"MostLikely": "Walking", "Confidence": 0.82}
        for k in ("MostLikely", "most_likely", "mostLikely"):
            if k in activity and isinstance(activity[k], str):
                conf = activity.get("Confidence") or activity.get("confidence")
                try:
                    conf = float(conf) if conf is not None else None
                except Exception:
                    conf = None
                return {"label": activity[k], "confidence": conf, "classes": activity}

        # 2) {"classification": "Walking", "confidence": 0.82}
        for k in ("classification", "activity", "label"):
            if k in activity and isinstance(activity[k], str):
                conf = activity.get("confidence") or activity.get("Confidence")
                try:
                    conf = float(conf) if conf is not None else None
                except Exception:
                    conf = None
                return {"label": activity[k], "confidence": conf, "classes": activity}

        # 3) dict of class->probability like {"Walking": 0.7, "Still": 0.2...}
        best_label = None
        best_conf = None
        any_numeric = False
        for k, v in activity.items():
            try:
                conf = float(v)
                any_numeric = True
            except Exception:
                conf = None

            if not any_numeric:
                continue

            if best_conf is None or (conf is not None and conf > best_conf):
                best_label = str(k)
                best_conf = conf

        if any_numeric and best_label is not None:
            return {"label": best_label, "confidence": best_conf, "classes": activity}

        # Fallback: first key as label
        first_key = next(iter(activity.keys()))
        return {"label": str(first_key), "confidence": None, "classes": activity}

    return {"label": "Unknown", "confidence": None, "classes": None}

class OrientationSensor:
    def __init__(self, event_bus, rate_hz: float = 50.0):
        self.bus = event_bus
        self.rate_hz = rate_hz
        self._next_t = 0.0
        self.bno = None

    def start(self):
        i2c = busio.I2C(board.I2C2_SCL, board.I2C2_SDA)
        self.bno = BNO08X_I2C(i2c)

        # Optional debug/future heading
        _try_enable(self.bno, getattr(adafruit_bno08x, "BNO_REPORT_ROTATION_VECTOR", None))

        # Useful signals
        _try_enable(self.bno, getattr(adafruit_bno08x, "BNO_REPORT_GYROSCOPE", None))
        _try_enable(self.bno, getattr(adafruit_bno08x, "BNO_REPORT_MAGNETOMETER", None))
        _try_enable(self.bno, getattr(adafruit_bno08x, "BNO_REPORT_LINEAR_ACCELERATION", None))
        _try_enable(self.bno, getattr(adafruit_bno08x, "BNO_REPORT_GRAVITY", None))

        # Optional classifier reports
        _try_enable(self.bno, getattr(adafruit_bno08x, "BNO_REPORT_STABILITY_CLASSIFIER", None))
        _try_enable(self.bno, getattr(adafruit_bno08x, "BNO_REPORT_ACTIVITY_CLASSIFIER", None))

        # Optional shake
        _try_enable(self.bno, getattr(adafruit_bno08x, "BNO_REPORT_SHAKE_DETECTOR", None))

        self._next_t = time.time()

    def update(self):
        if self.bno is None:
            return

        now = time.time()
        if now < self._next_t:
            return
        self._next_t = now + (1.0 / self.rate_hz)

        # ---- Tilt (gravity) ----
        try:
            g = self.bno.gravity
            if g is not None:
                gx, gy, gz = g
                roll_deg, pitch_deg, tilt_deg = _tilt_from_gravity(gx, gy, gz)

                stability = _safe_read(lambda: self.bno.stability_classification, None)
                activity_raw = _safe_read(lambda: self.bno.activity_classification, None)
                activity = _pick_activity_label(activity_raw)

                tilt_payload = {
                    "roll_deg": roll_deg,
                    "pitch_deg": pitch_deg,
                    "tilt_deg": tilt_deg,
                }
                if stability is not None:
                    tilt_payload["stability"] = stability
                if activity is not None:
                    tilt_payload["activity"] = activity  # dict with label/conf/classes

                self.bus.emit("imu_tilt", tilt_payload)
        except Exception as e:
            print(f"[IMU] warn: gravity read failed: {e}")

        # ---- Motion ----
        motion = {}

        # Shake latch
        try:
            if getattr(self.bno, "shake", None):
                motion["shake"] = True
        except Exception:
            pass

        # Linear accel
        try:
            la = self.bno.linear_acceleration
            if la is not None:
                motion["lin_accel_mps2"] = la
        except Exception:
            pass

        # Gyro
        try:
            gyro = self.bno.gyro
            if gyro is not None:
                motion["gyro_rads"] = gyro
        except Exception:
            pass

        # Magnetometer
        try:
            mag = self.bno.magnetic
            if mag is not None:
                motion["mag_uT"] = mag
        except Exception:
            pass

        # Emit only when meaningful
        emit = False
        if motion.get("shake"):
            emit = True
        if "lin_accel_mps2" in motion:
            lax, lay, laz = motion["lin_accel_mps2"]
            if (lax*lax + lay*lay + laz*laz) ** 0.5 > 3.0:
                emit = True

        if emit:
            self.bus.emit("imu_motion", motion)

        # Optional quat
        try:
            q = self.bno.quaternion
            if q is not None:
                self.bus.emit("imu_quat", q)
        except Exception:
            pass
