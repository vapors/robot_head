import board
import digitalio
import busio
import sys
import adafruit_platformdetect


print("Hello blinka!")

detector = adafruit_platformdetect.Detector()
chip_id = detector.chip.id
board_id = detector.board.id

print(chip_id)
print(board_id)
# Try to great a Digital input
pin = digitalio.DigitalInOut(board.D7)
print("Digital IO ok!")
# Create I2C bus
i2c = busio.I2C(board.SCL, board.SDA)

# Lock the bus for scanning
while not i2c.try_lock():
    pass

try:
    print("Scanning I2C bus...")
    # Scan for devices
    devices = i2c.scan()
    print("I2C addresses found:", [hex(device_address) for device_address in devices])
finally:
    # Unlock the bus
    i2c.unlock()
    
# Try to create an SPI device
spi = busio.SPI(board.SCLK, board.MOSI, board.MISO)
print("SPI ok!")

print("done!")
