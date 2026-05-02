# face/renderer.py
import math
from dataclasses import dataclass

@dataclass
class _Layer:
    name: str = "idle"
    weight: float = 1.0  # 0..1

class FaceRenderer:
    """Very lightweight face 'renderer'.

    Today it just prints state changes, but the API is shaped so we can later
    drive:
      - viseme mouth shapes (audio)
      - gaze/eye offsets (vision / person_focus)
      - expression blending (emotion base + reaction overlay)
    """

    def __init__(self):
        # Base emotion / idle expression
        self._base = _Layer("idle", 1.0)

        # Short-lived reaction overlay (startle, dizzy, etc.)
        self._overlay = _Layer("idle", 0.0)

        # Micro motion channels (degrees for now; later could be normalized)
        self.head_roll_deg = 0.0
        self.head_pitch_deg = 0.0

        # What we *actually* show right now (debug output)
        self._shown_expression = None

    # --- High-level controls -------------------------------------------------
    def set_base_expression(self, name: str, weight: float = 1.0):
        self._base.name = name
        self._base.weight = max(0.0, min(1.0, weight))

    def trigger_overlay(self, name: str, strength: float = 1.0):
        """Start/refresh a short-lived overlay reaction."""
        self._overlay.name = name
        self._overlay.weight = max(self._overlay.weight, max(0.0, min(1.0, strength)))

    def set_head_pose(self, roll_deg: float | None = None, pitch_deg: float | None = None):
        if roll_deg is not None:
            self.head_roll_deg = float(roll_deg)
        if pitch_deg is not None:
            self.head_pitch_deg = float(pitch_deg)

    # Backwards-compatible call (old code)
    def set_expression(self, name: str):
        self.set_base_expression(name)

    # --- Main update ---------------------------------------------------------
    def update(self, dt: float):
        # Decay overlay slowly; this is our simplest "blending" primitive.
        self._overlay.weight = max(0.0, self._overlay.weight - (dt * 1.5))  # ~0.6s full fade

        # Decide what to "show"
        if self._overlay.weight > 0.15:
            shown = f"{self._base.name} + {self._overlay.name}({self._overlay.weight:.2f})"
        else:
            shown = self._base.name

        # Only print on change to keep logs readable
        if shown != self._shown_expression:
            self._shown_expression = shown
            print(f"[FACE] expression → {shown}")

        # Print micro pose at a low rate (optional; keep noise down)
        # (Later this will drive rig offsets rather than spam logs.)
        # If you want this always-on, remove the threshold checks.
        if abs(self.head_roll_deg) > 1 or abs(self.head_pitch_deg) > 1:
            print(f"[FACE] micro_pose roll={self.head_roll_deg:+.1f}° pitch={self.head_pitch_deg:+.1f}°")
