#!/usr/bin/env python3

import argparse
import os
import sys
import time
from pathlib import Path


DEFAULT_BAUD = 1000000
MIN_SERVO_ID = 0
MAX_SERVO_ID = 254


def parse_args():
    default_baud = DEFAULT_BAUD
    env_baud = os.environ.get("BAUD")
    if env_baud:
        try:
            default_baud = int(env_baud)
        except ValueError:
            raise SystemExit("BAUD must be an integer")

    parser = argparse.ArgumentParser(
        description="Assign a new ID to one STServo/SCServo serial-bus servo.",
        epilog="Only connect one unassigned servo while changing IDs.",
    )
    parser.add_argument(
        "--port",
        default=os.environ.get("SERIAL_PORT"),
        help="Serial adapter path, e.g. /dev/tty.usbserial-1234 or COM3.",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=default_baud,
        help=f"Serial baud rate. Defaults to BAUD or {DEFAULT_BAUD}.",
    )
    parser.add_argument(
        "--old-id",
        type=int,
        required=True,
        help="Current servo ID.",
    )
    parser.add_argument(
        "--new-id",
        type=int,
        required=True,
        help="New servo ID to write.",
    )
    parser.add_argument(
        "--family",
        choices=("sms_sts", "scscl"),
        default="sms_sts",
        help="Servo register layout. Use sms_sts for STS/SMS_STS servos.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Write even if the new ID already answers on the bus.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Do not ping the new ID after writing.",
    )
    return parser.parse_args()


def require_id(name, value):
    if value < MIN_SERVO_ID or value > MAX_SERVO_ID:
        raise SystemExit(f"{name} must be between {MIN_SERVO_ID} and {MAX_SERVO_ID}")


def load_sdk():
    sdk_root = Path(__file__).resolve().parent / "STServo_Python"
    sys.path.insert(0, str(sdk_root))
    try:
        import scservo_sdk as sdk
    except ModuleNotFoundError as exc:
        if exc.name == "serial":
            raise SystemExit(
                "pyserial is missing. Install it with: "
                "python3 -m pip install -r python/STServo_Python/requirements.txt"
            ) from exc
        raise SystemExit(f"Could not import SCServo SDK from {sdk_root}") from exc
    return sdk


def result_message(handler, result, error):
    if result != 0:
        return handler.getTxRxResult(result)
    if error != 0:
        return handler.getRxPacketError(error)
    return "ok"


def check_result(handler, action, result, error):
    if result != 0 or error != 0:
        raise RuntimeError(f"{action} failed: {result_message(handler, result, error)}")


def make_handler(sdk, family, port_handler):
    if family == "sms_sts":
        return sdk.sms_sts(port_handler), sdk.SMS_STS_ID
    if family == "scscl":
        return sdk.scscl(port_handler), sdk.scs_id
    raise AssertionError(f"unsupported family: {family}")


def patch_pyserial_write(port_handler):
    original_write = port_handler.writePort

    def write_port(packet):
        if isinstance(packet, list):
            packet = bytes(packet)
        return original_write(packet)

    port_handler.writePort = write_port


def checksum(packet):
    return (~(sum(packet[2:]) & 0xFF)) & 0xFF


def raw_ping_id(port_handler, servo_id, timeout_ms=80):
    packet = bytes([0xFF, 0xFF, servo_id, 0x02, 0x01, checksum([0xFF, 0xFF, servo_id, 0x02, 0x01])])
    try:
        port_handler.ser.reset_input_buffer()
    except Exception:
        pass
    port_handler.ser.write(packet)
    port_handler.ser.flush()

    deadline = time.monotonic() + timeout_ms / 1000.0
    data = bytearray()
    while time.monotonic() < deadline:
        waiting = port_handler.ser.in_waiting
        chunk = port_handler.ser.read(waiting or 1)
        if chunk:
            data.extend(chunk)
        while len(data) >= 2:
            header = data.find(b"\xff\xff")
            if header < 0:
                data.clear()
                break
            if header > 0:
                del data[:header]
            if len(data) < 4:
                break
            packet_len = data[3] + 4
            if packet_len < 6 or packet_len > 250:
                del data[0]
                continue
            frame = data[:packet_len]
            del data[:packet_len]
            if frame[2] != servo_id:
                continue
            expected = checksum(frame[:-1])
            if frame[-1] == expected:
                return True
    return False


def lock_eprom_best_effort(handler, old_id, new_id):
    for servo_id in (new_id, old_id):
        result, error = handler.LockEprom(servo_id)
        if result == 0 and error == 0:
            return servo_id
    return None


def main():
    args = parse_args()
    if not args.port:
        raise SystemExit("--port is required, or set SERIAL_PORT")
    if args.old_id == args.new_id:
        raise SystemExit("--old-id and --new-id must differ")
    require_id("--old-id", args.old_id)
    require_id("--new-id", args.new_id)
    if args.baud <= 0:
        raise SystemExit("--baud must be positive")

    sdk = load_sdk()
    port_handler = sdk.PortHandler(args.port)
    patch_pyserial_write(port_handler)
    handler, id_register = make_handler(sdk, args.family, port_handler)

    try:
        if not port_handler.openPort():
            raise RuntimeError(f"failed to open {args.port}")
        if not port_handler.setBaudRate(args.baud):
            raise RuntimeError(f"failed to set baud rate {args.baud}")

        if not raw_ping_id(port_handler, args.old_id):
            raise RuntimeError(f"old ID {args.old_id} did not respond")
        print(f"old ID {args.old_id} responded")

        if raw_ping_id(port_handler, args.new_id) and not args.force:
            raise RuntimeError(
                f"new ID {args.new_id} already responds; "
                "use --force only when you are sure one servo is connected"
            )

        result, error = handler.unLockEprom(args.old_id)
        check_result(handler, f"unlock EEPROM on ID {args.old_id}", result, error)

        result, error = handler.write1ByteTxRx(args.old_id, id_register, args.new_id)
        check_result(handler, f"write new ID {args.new_id}", result, error)
        time.sleep(0.1)

        locked_id = lock_eprom_best_effort(handler, args.old_id, args.new_id)
        if locked_id is None:
            print("warning: ID changed, but EEPROM lock command did not get a reply")
        else:
            print(f"EEPROM locked via ID {locked_id}")

        if not args.skip_verify:
            if not raw_ping_id(port_handler, args.new_id):
                raise RuntimeError(f"new ID {args.new_id} did not respond")
            print(f"new ID {args.new_id} responded")

        print(f"changed servo ID {args.old_id} -> {args.new_id}")
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if port_handler.is_open:
            port_handler.closePort()


if __name__ == "__main__":
    raise SystemExit(main())
