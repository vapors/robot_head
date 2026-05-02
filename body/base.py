# body/base.py

class BodyBase:
    name = "unknown"

    def stop(self):
        print("[BODY] stop")

    def move(self, vx=0.0, vy=0.0, yaw_rate=0.0):
        print(f"[BODY] move vx={vx} vy={vy} yaw={yaw_rate}")
