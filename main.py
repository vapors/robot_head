# main.py
import time
from shared.events import EventBus
from face.renderer import FaceRenderer
from behavior.reactions import BehaviorController
from body.manager import BodyManager

from sensors.imu import OrientationSensor
from sensors.proximity import ProximitySensor

def main():
    print("🤖 Robot head starting up...")

    bus = EventBus()
    face = FaceRenderer()
    body = BodyManager().get_body()
    behavior = BehaviorController(face, body)

    # --- Wire events ---
    bus.subscribe("person_focus", behavior.on_person_focus)

    # IMU: higher-level signals (tilt/motion) + optional quat debug
    bus.subscribe("imu_tilt", behavior.on_imu_tilt)
    bus.subscribe("imu_motion", behavior.on_imu_motion)
    # bus.subscribe("imu_quat", lambda q: print(f"[DBG] imu_quat: {q}"))

    imu = OrientationSensor(bus, rate_hz=50.0)
    radar = ProximitySensor(bus, port="/dev/ttyS3", baud=256000)

    imu.start()
    radar.start()

    print(f"[SYSTEM] active body: {body.name}")
    face.set_base_expression("idle")

    last = time.time()
    try:
        while True:
            now = time.time()
            dt = now - last
            last = now

            imu.update()
            radar.update()

            # NEW: a real behavior tick (breathing, emotion decay, blending)
            behavior.update(dt)

            face.update(dt)
            time.sleep(0.005)  # small yield
    finally:
        radar.close()

if __name__ == "__main__":
    main()
