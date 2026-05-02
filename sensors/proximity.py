# sensors/proximity.py
import time
import math
import serial
from sensors import serial_protocol


class ProximitySensor:
    """
    HLK-LD2450 proximity / person tracking wrapper (SIMPLIFIED).

    The only outputs are:
      - "mmwave_targets_simple": list of 3 dicts (one per target)
      - "person_focus": dict describing the selected target (closest)
      - "person_near": float meters (focused target range) or None

    Notes:
      - angle is computed from x/y using atan2(x, y) so:
          * 0° = straight ahead (y+)
          * negative = left, positive = right  (unless you flip it)
    """

    # --- tuning knobs (keep these few) ---
    DEADZONE_DEG = 6.0           # angles within +/- this are treated as "center"
    ABS_LIMIT_MM = 20000         # discard absurd values
    HOLD_SEC = 0.25              # keep last focus briefly if target drops
    ALPHA_RANGE = 0.35           # smoothing for range/angle
    ALPHA_ANGLE = 0.50

    # If you discover your coordinate system is mirrored, flip this:
    INVERT_X = False

    def __init__(self, event_bus, port="/dev/ttyS3", baud=256000):
        self.bus = event_bus
        self.port = port
        self.baud = baud
        self.ser = None

        self._buf = bytearray()

        # hold + smoothing state for "focus"
        self._last_focus = None
        self._last_focus_time = 0.0
        self._range_smooth = None
        self._angle_smooth = None

    def start(self):
        self.ser = serial.Serial(self.port, self.baud, timeout=0.05)

    def close(self):
        if self.ser:
            self.ser.close()
            self.ser = None

    # -----------------------------
    # Helpers
    # -----------------------------

    def _valid_target(self, x, y, sp, res) -> bool:
        if (x, y, sp, res) == (0, 0, 0, 0):
            return False
        if abs(x) > self.ABS_LIMIT_MM or abs(y) > self.ABS_LIMIT_MM:
            return False
        return True

    def _side_from_angle(self, angle_deg: float) -> str:
        if angle_deg < -self.DEADZONE_DEG:
            return "left"
        if angle_deg > self.DEADZONE_DEG:
            return "right"
        return "center"

    def _compute_metrics(self, x_mm: int, y_mm: int):
        if self.INVERT_X:
            x_mm = -x_mm

        range_m = math.hypot(x_mm, y_mm) / 1000.0
        angle_deg = math.degrees(math.atan2(x_mm, y_mm))  # x left/right, y forward

        return x_mm, y_mm, range_m, angle_deg

    def _pick_focus_index(self, targets):
        """
        Pick the closest valid target by range.
        targets: list[(x,y,sp,res)] length 3
        returns: index or None
        """
        best = None
        for i, (x, y, sp, res) in enumerate(targets):
            if not self._valid_target(x, y, sp, res):
                continue
            _, _, range_m, _ = self._compute_metrics(x, y)
            if best is None or range_m < best[0]:
                best = (range_m, i)
        return None if best is None else best[1]

    def _emit_no_target(self):
        now = time.time()
        if self._last_focus and (now - self._last_focus_time) < self.HOLD_SEC:
            held = dict(self._last_focus)
            held["present"] = True
            held["held"] = True
            self.bus.emit("person_focus", held)
            self.bus.emit("person_near", held.get("range_m"))
            return

        self._last_focus = None
        self._range_smooth = None
        self._angle_smooth = None

        self.bus.emit("person_focus", {"present": False})
        self.bus.emit("person_near", None)

    # -----------------------------
    # Main update loop
    # -----------------------------

    def update(self):
        if not self.ser:
            return

        # Read bytes and append to rolling buffer
        data = self.ser.read(256)
        if data:
            self._buf.extend(data)

        while True:
            start = self._buf.find(serial_protocol.REPORT_HEADER)
            if start < 0:
                # keep buffer from growing forever
                if len(self._buf) > 2048:
                    del self._buf[:-64]
                return

            end = start + serial_protocol.REPORT_FRAME_LEN
            if len(self._buf) < end:
                # wait for more bytes, but drop junk before header
                if start > 0:
                    del self._buf[:start]
                return

            frame = bytes(self._buf[start:end])
            del self._buf[:end]

            if frame[-2:] != serial_protocol.REPORT_TAIL:
                continue

            values = serial_protocol.read_radar_data(frame)
            if values is None:
                continue

            # Unpack 3 targets (x, y, speed, res)
            targets = [values[0:4], values[4:8], values[8:12]]

            # Build simplified per-target list (always length 3)
            simple = []
            for (x, y, sp, res) in targets:
                if self._valid_target(x, y, sp, res):
                    x2, y2, r_m, a_deg = self._compute_metrics(x, y)
                    simple.append({
                        "present": True,
                        "x_mm": x2,
                        "y_mm": y2,
                        "range_m": r_m,
                        "angle_deg": a_deg,
                        "side": self._side_from_angle(a_deg),
                    })
                else:
                    simple.append({"present": False})

            self.bus.emit("mmwave_targets_simple", simple)

            # Focus selection
            focus_idx = self._pick_focus_index(targets)
            if focus_idx is None:
                self._emit_no_target()
                return

            f = simple[focus_idx]
            # Smooth range + angle for stability
            if self._range_smooth is None:
                self._range_smooth = float(f["range_m"])
                self._angle_smooth = float(f["angle_deg"])
            else:
                self._range_smooth = (1 - self.ALPHA_RANGE) * self._range_smooth + self.ALPHA_RANGE * float(f["range_m"])
                self._angle_smooth = (1 - self.ALPHA_ANGLE) * self._angle_smooth + self.ALPHA_ANGLE * float(f["angle_deg"])

            focus = {
                "present": True,
                "held": False,
                "idx": focus_idx,
                "range_m": self._range_smooth,
                "angle_deg": self._angle_smooth,
                "side": self._side_from_angle(self._angle_smooth),
                # keep raw-ish x/y around in case you want to map yaw by mm instead of degrees
                "x_mm": f.get("x_mm", 0),
                "y_mm": f.get("y_mm", 0),
            }

            self._last_focus = focus
            self._last_focus_time = time.time()

            self.bus.emit("person_focus", focus)
            self.bus.emit("person_near", focus["range_m"])
            return
