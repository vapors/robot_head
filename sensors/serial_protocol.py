# serial_protocol.py
from __future__ import annotations

import serial
from dataclasses import dataclass
from typing import Optional, Tuple, List

# ============================
# Constants
# ============================

COMMAND_HEADER = bytes.fromhex("FD FC FB FA")
COMMAND_TAIL   = bytes.fromhex("04 03 02 01")

REPORT_HEADER  = bytes.fromhex("AA FF 03 00")
REPORT_TAIL    = bytes.fromhex("55 CC")

REPORT_FRAME_LEN = 30
TARGET_COUNT = 3
TARGET_LEN = 8  # x(2) y(2) speed(2) res(2)


# ============================
# LD2450 "signed int16" decode
# ============================

def _s15_signmag_le(b: bytes) -> int:
    """
    LD2450 uses a nonstandard "signed int16" representation:
      - bit15 (MSB) indicates sign: 1 => positive, 0 => negative
      - bits14..0 are magnitude
    This is *not* two's complement, so signed=True is wrong.

    Example from datasheet: 0x86B1 -> +1713 (since 0x86B1 - 0x8000 = 0x06B1)
    """
    raw = int.from_bytes(b, byteorder="little", signed=False)  # 0..65535
    mag = raw & 0x7FFF
    pos = (raw & 0x8000) != 0
    return mag if pos else -mag


def _u16_le(b: bytes) -> int:
    return int.from_bytes(b, byteorder="little", signed=False)


# ============================
# Data structures (optional)
# ============================

@dataclass(frozen=True)
class Target:
    x_mm: int
    y_mm: int
    speed_cms: int
    dist_res_mm: int

    def is_empty(self) -> bool:
        return (self.x_mm, self.y_mm, self.speed_cms, self.dist_res_mm) == (0, 0, 0, 0)


@dataclass(frozen=True)
class RadarReport:
    targets: Tuple[Target, Target, Target]


# ============================
# Frame extraction + parsing
# ============================

def find_report_frame(buf: bytes) -> Optional[bytes]:
    """
    Find a single complete 30-byte report frame within an arbitrary bytes buffer.
    Returns the 30-byte frame or None.
    """
    start = buf.find(REPORT_HEADER)
    if start < 0:
        return None

    end = start + REPORT_FRAME_LEN
    if len(buf) < end:
        return None

    frame = buf[start:end]
    if frame[-2:] != REPORT_TAIL:
        return None

    return frame


def parse_report_frame(frame: bytes) -> RadarReport:
    """
    Parse a validated 30-byte frame into structured targets.
    Raises ValueError if invalid.
    """
    if len(frame) != REPORT_FRAME_LEN:
        raise ValueError(f"Invalid frame length {len(frame)} != {REPORT_FRAME_LEN}")
    if not frame.startswith(REPORT_HEADER):
        raise ValueError("Missing REPORT_HEADER")
    if frame[-2:] != REPORT_TAIL:
        raise ValueError("Missing REPORT_TAIL")

    payload = frame[4:-2]  # 24 bytes: 3 targets * 8 bytes
    targets: List[Target] = []

    for i in range(TARGET_COUNT):
        off = i * TARGET_LEN
        t = payload[off:off + TARGET_LEN]

        x = _s15_signmag_le(t[0:2])
        y = _s15_signmag_le(t[2:4])
        speed = _s15_signmag_le(t[4:6])
        dist_res = _u16_le(t[6:8])

        targets.append(Target(x_mm=x, y_mm=y, speed_cms=speed, dist_res_mm=dist_res))

    return RadarReport(targets=(targets[0], targets[1], targets[2]))


def read_radar_data(serial_port_line: bytes) -> Optional[Tuple[int, ...]]:
    """
    Backward-compatible helper used by your ProximitySensor.

    Returns a tuple of 12 ints:
      (x1, y1, sp1, res1, x2, y2, sp2, res2, x3, y3, sp3, res3)
    or None if no valid frame is found in the provided bytes.

    IMPORTANT:
    - Robust to extra bytes (does not require len == 30)
    - Uses LD2450 sign-bit+magnitude decoding (NOT two's complement)
    """
    frame = find_report_frame(serial_port_line)
    if frame is None:
        return None

    report = parse_report_frame(frame)
    out: List[int] = []
    for t in report.targets:
        out.extend([t.x_mm, t.y_mm, t.speed_cms, t.dist_res_mm])
    return tuple(out)


# ============================
# Command helpers (your existing API)
# ============================

def _send_command(
    ser: serial.Serial,
    intra_frame_length: bytes,
    command_word: bytes,
    command_value: bytes
) -> bytes:
    """
    Send a command to the radar (see docs 2.1.2)
    """
    command = COMMAND_HEADER + intra_frame_length + command_word + command_value + COMMAND_TAIL
    ser.write(command)
    response = ser.read_until(COMMAND_TAIL)
    return response


def _get_command_success(response: bytes) -> bool:
    """
    Check if the command was sent successfully.
    """
    if response is None or len(response) < 10:
        return False
    success_int = int.from_bytes(response[8:10], byteorder="little", signed=True)
    return (success_int == 0)


def enable_configuration_mode(ser: serial.Serial) -> bool:
    """
    Set the radar to configuration mode (docs 2.2.1)
    """
    intra_frame_length = int(4).to_bytes(2, byteorder="little", signed=True)
    command_word = bytes.fromhex("FF 00")
    command_value = bytes.fromhex("01 00")

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    print("Configuration mode enabled" if ok else "Configuration enable failed")
    return ok


def end_configuration_mode(ser: serial.Serial) -> bool:
    """
    End the configuration mode (docs 2.2.2)
    """
    intra_frame_length = int(2).to_bytes(2, byteorder="little", signed=False)
    command_word = bytes.fromhex("FE 00")
    command_value = bytes.fromhex("")

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    print("Configuration mode disabled" if ok else "Configuration disable failed")
    return ok


def single_target_tracking(ser: serial.Serial) -> bool:
    """
    Single target tracking mode (docs 2.2.3)
    """
    intra_frame_length = int(2).to_bytes(2, byteorder="little", signed=True)
    command_word = bytes.fromhex("80 00")
    command_value = bytes.fromhex("")

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    print("Single target tracking mode enabled" if ok else "Single target tracking mode enable failed")
    return ok


def multi_target_tracking(ser: serial.Serial) -> bool:
    """
    Multi target tracking mode (docs 2.2.4)
    """
    intra_frame_length = int(2).to_bytes(2, byteorder="little", signed=True)
    command_word = bytes.fromhex("90 00")
    command_value = bytes.fromhex("")

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    print("Multi target tracking mode enabled" if ok else "Multi target tracking mode enable failed")
    return ok


def query_target_tracking(ser: serial.Serial) -> Optional[int]:
    """
    Query tracking mode (docs 2.2.5)
    Returns 1 for single, 2 for multi.
    """
    intra_frame_length = int(2).to_bytes(2, byteorder="little", signed=True)
    command_word = bytes.fromhex("91 00")
    command_value = bytes.fromhex("")

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    if not ok or response is None or len(response) < 12:
        print("Query target tracking mode failed")
        return None

    tracking_type_int = int.from_bytes(response[10:12], byteorder="little", signed=True)
    print(f"Tracking mode: {tracking_type_int}")
    return tracking_type_int


def read_firmware_version(ser: serial.Serial) -> Optional[str]:
    """
    Read firmware version (docs 2.2.6)
    """
    intra_frame_length = int(2).to_bytes(2, byteorder="little", signed=True)
    command_word = bytes.fromhex("A0 00")
    command_value = bytes.fromhex("")

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    if not ok or response is None or len(response) < 18:
        print("Read firmware version failed")
        return None

    firmware_type = int.from_bytes(response[10:12], byteorder="little", signed=True)
    major_version_number = int.from_bytes(response[12:14], byteorder="little", signed=True)
    minor_version_number = int.from_bytes(response[14:18], byteorder="little", signed=True)
    firmware_version = f"V{firmware_type}.{major_version_number}.{minor_version_number}"
    print(f"Firmware version: {firmware_version}")
    return firmware_version


def set_serial_port_baud_rate(ser: serial.Serial, baud_rate: int = 256000) -> bool:
    """
    Set serial port baud rate (docs 2.2.7)
    """
    possible_baud_rates = [9600, 19200, 38400, 57600, 115200, 230400, 256000, 460800]
    if baud_rate not in possible_baud_rates:
        raise ValueError(f"baud_rate must be one of: {possible_baud_rates}")

    intra_frame_length = int(4).to_bytes(2, byteorder="little", signed=True)
    command_word = bytes.fromhex("A1 00")
    baudrate_index = possible_baud_rates.index(baud_rate)
    command_value = int(baudrate_index).to_bytes(2, byteorder="little", signed=False)

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    print(f"Serial port baud rate set to {baud_rate}" if ok else "Set serial port baud rate failed")
    return ok


def restore_factory_settings(ser: serial.Serial) -> bool:
    """
    Restore factory settings (docs 2.2.8)
    """
    intra_frame_length = int(2).to_bytes(2, byteorder="little", signed=False)
    command_word = bytes.fromhex("A2 00")
    command_value = bytes.fromhex("")

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    print("Factory settings restored" if ok else "Restore factory settings failed")
    return ok


def restart_module(ser: serial.Serial) -> bool:
    """
    Restart module (docs 2.2.9)
    """
    intra_frame_length = int(2).to_bytes(2, byteorder="little", signed=False)
    command_word = bytes.fromhex("A3 00")
    command_value = bytes.fromhex("")

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    print("Module restarted" if ok else "Module restart failed")
    return ok


def bluetooth_setup(ser: serial.Serial, bluetooth_on: bool = True) -> bool:
    """
    Bluetooth setup (docs 2.2.10)
    """
    intra_frame_length = int(4).to_bytes(2, byteorder="little", signed=False)
    command_word = bytes.fromhex("A4 00")
    command_value = bytes.fromhex("01 00") if bluetooth_on else bytes.fromhex("00 00")

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    print(f'Bluetooth {"enabled" if bluetooth_on else "disabled"}' if ok else "Bluetooth setup failed")
    return ok


def get_mac_address(ser: serial.Serial) -> Optional[str]:
    """
    Get MAC address (docs 2.2.11)
    NOTE: Your original code decoded response[10:22] as utf-8.
    Some devices may return raw bytes. Keep as-is for now.
    """
    intra_frame_length = int(4).to_bytes(2, byteorder="little", signed=False)
    command_word = bytes.fromhex("A5 00")
    command_value = bytes.fromhex("01 00")

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    if not ok or response is None or len(response) < 22:
        print("Get MAC address failed")
        return None

    try:
        mac_address = response[10:22].decode("utf-8")
    except Exception:
        mac_address = response[10:22].hex()
    print(f"MAC address: {mac_address}")
    return mac_address


def query_zone_filtering(ser: serial.Serial):
    """
    Query zone filtering (docs 2.2.12)
    Returns a 13-tuple or None.
    """
    intra_frame_length = int(2).to_bytes(2, byteorder="little", signed=False)
    command_word = bytes.fromhex("C1 00")
    command_value = bytes.fromhex("")

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    if not ok or response is None or len(response) < 36:
        print("Query zone filtering mode failed")
        return None

    zone_filtering_mode = int.from_bytes(response[10:12], byteorder="little", signed=True)
    region1_x1 = int.from_bytes(response[12:14], byteorder="little", signed=True)
    region1_y1 = int.from_bytes(response[14:16], byteorder="little", signed=True)
    region1_x2 = int.from_bytes(response[16:18], byteorder="little", signed=True)
    region1_y2 = int.from_bytes(response[18:20], byteorder="little", signed=True)
    region2_x1 = int.from_bytes(response[20:22], byteorder="little", signed=True)
    region2_y1 = int.from_bytes(response[22:24], byteorder="little", signed=True)
    region2_x2 = int.from_bytes(response[24:26], byteorder="little", signed=True)
    region2_y2 = int.from_bytes(response[26:28], byteorder="little", signed=True)
    region3_x1 = int.from_bytes(response[28:30], byteorder="little", signed=True)
    region3_y1 = int.from_bytes(response[30:32], byteorder="little", signed=True)
    region3_x2 = int.from_bytes(response[32:34], byteorder="little", signed=True)
    region3_y2 = int.from_bytes(response[34:36], byteorder="little", signed=True)

    print(f"Zone filtering mode: {zone_filtering_mode}")
    return (
        zone_filtering_mode,
        region1_x1, region1_y1, region1_x2, region1_y2,
        region2_x1, region2_y1, region2_x2, region2_y2,
        region3_x1, region3_y1, region3_x2, region3_y2
    )


def set_zone_filtering(
    ser: serial.Serial,
    zone_filtering_mode: int = 0,
    region1_x1: int = 0, region1_y1: int = 0, region1_x2: int = 0, region1_y2: int = 0,
    region2_x1: int = 0, region2_y1: int = 0, region2_x2: int = 0, region2_y2: int = 0,
    region3_x1: int = 0, region3_y1: int = 0, region3_x2: int = 0, region3_y2: int = 0
) -> bool:
    """
    Set zone filtering (docs 2.2.13)

    NOTE: This function uses bytes.fromhex with formatted values.
    If you pass negative region coords, the formatting here may not encode them correctly.
    Keep your usage to non-negative unless you update this encoding method later.
    """
    intra_frame_length = int(26).to_bytes(2, byteorder="little", signed=False)
    command_word = bytes.fromhex("C2 00")
    command_value = bytes.fromhex(
        f"{zone_filtering_mode:04x} "
        f"{region1_x1:04x} {region1_y1:04x} {region1_x2:04x} {region1_y2:04x} "
        f"{region2_x1:04x} {region2_y1:04x} {region2_x2:04x} {region2_y2:04x} "
        f"{region3_x1:04x} {region3_y1:04x} {region3_x2:04x} {region3_y2:04x}"
    )

    response = _send_command(ser, intra_frame_length, command_word, command_value)
    ok = _get_command_success(response)
    print(f"Zone filtering mode set to {zone_filtering_mode}" if ok else "Set zone filtering mode failed")
    return ok
