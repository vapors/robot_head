import time
import board
import busio
import adafruit_bno08x
from adafruit_bno08x.i2c import BNO08X_I2C

# Initialize I2C bus
# For a Raspberry Pi, the default I2C bus is typically 1.
# For other boards, check your documentation for the correct pins.
i2c = busio.I2C(board.I2C2_SCL, board.I2C2_SDA)

# Initialize BNO08X sensor using I2C
# The default I2C address is 0x4A.
# Make sure to define your INT and RST pins if they are not the defaults
# specified in the library (though explicit definition is recommended).
# You may need to wire up the RST pin to a specific GPIO to ensure proper power-on reset.
bno = BNO08X_I2C(i2c) # Example pins for RST and INT

# Enable the rotation vector report
bno.enable_feature(adafruit_bno08x.BNO_REPORT_ROTATION_VECTOR)
bno.enable_feature(adafruit_bno08x.BNO_REPORT_GRAVITY )

print("Reading BNO085 data...")

while True:
    # Get the quaternion data
    quat_i, quat_j, quat_k, quat_real = bno.quaternion
    gx, gy, gz = bno.gravity 
    # Print the values
    #print(f"Quaternion: i={quat_i:0.4f}, j={quat_j:0.4f}, k={quat_k:0.4f}, real={quat_real:0.4f}")
    print(f"Quaternion: gx={gx:0.4f}, gy={gy:0.4f}, gz={gz:0.4f}")
    
    # Optional: read other data types if enabled
    # print(f"Temperature: {bno.temperature} C")

    time.sleep(0.1)
