# behavior/state.py
from dataclasses import dataclass

@dataclass
class EmotionalState:
    """Tiny emotion model (expand later).

    valence:  -1..+1  (sad → happy)
    arousal:   0..1   (calm → excited)
    """
    valence: float = 0.0
    arousal: float = 0.2

    # Optional: a human-readable label you can log / map to expressions
    label: str = "neutral"

    def decay_toward_baseline(self, dt: float, baseline_valence: float = 0.0, baseline_arousal: float = 0.15):
        # Gentle drift back to baseline
        k = 0.35  # per-second
        self.valence += (baseline_valence - self.valence) * (1.0 - pow(2.71828, -k * dt))
        self.arousal += (baseline_arousal - self.arousal) * (1.0 - pow(2.71828, -k * dt))

        # Clamp
        self.valence = max(-1.0, min(1.0, self.valence))
        self.arousal = max(0.0, min(1.0, self.arousal))
