#!/usr/bin/env python3

import argparse
import os
import sys
import time
from pathlib import Path


DEFAULT_BAUD = 1000000
AUTO_BAUDS = (1000000, 500000, 250000, 128000, 115200, 76800, 57600, 38400, 19200, 9600, 4800)
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
        description="Scan an STServo/SCServo serial bus and print responding IDs."
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
        "--start-id",
        type=int,
        default=MIN_SERVO_ID,
        help=f"First ID to scan. Defaults to {MIN_SERVO_ID}.",
    )
    parser.add_argument(
        "--end-id",
        type=int,
        default=MAX_SERVO_ID,
        help=f"Last ID to scan. Defaults to {MAX_SERVO_ID}.",
    )
    parser.add_argument(
        "--family",
        choices=("sms_sts", "scscl", "both"),
        default="sms_sts",
        help="Servo register layout. Use sms_sts for STS/SMS_STS servos.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Try both families and common baud rates.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print model numbers next to found IDs.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print progress or summary messages to stderr.",
    )
    parser.add_argument(
        "--debug-errors",
        action="store_true",
        help="Print per-ID communication/parser errors to stderr.",
    )
    parser.add_argument(
        "--sdk-ping",
        action="store_true",
        help="Use the SDK ping method, which also reads the model number.",
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


def make_handler(sdk, family, port_handler):
    if family == "sms_sts":
        return sdk.sms_sts(port_handler)
    if family == "scscl":
        return sdk.scscl(port_handler)
    raise AssertionError(f"unsupported family: {family}")


def patch_pyserial_write(port_handler):
    original_write = port_handler.writePort

    def write_port(packet):
        if isinstance(packet, list):
            packet = bytes(packet)
        return original_write(packet)

    port_handler.writePort = write_port


def ping_id(handler, servo_id):
    try:
        model, result, error = handler.ping(servo_id)
    except (IndexError, ValueError, TypeError):
        return None, None, None
    return model, result, error


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
            if len(data) < packet_len:
                break
            frame = data[:packet_len]
            del data[:packet_len]
            if frame[2] != servo_id:
                continue
            expected = checksum(frame[:-1])
            if frame[-1] == expected:
                return True
    return False


def scan_bus(args, port_handler, handler, family, baud):
    found = []
    total = args.end_id - args.start_id + 1
    ping_mode = family if args.sdk_ping else "raw"
    if not args.quiet:
        print(
            f"scanning IDs {args.start_id}..{args.end_id} on {args.port} "
            f"at {baud} baud using {ping_mode}",
            file=sys.stderr,
            flush=True,
        )

    for offset, servo_id in enumerate(range(args.start_id, args.end_id + 1), 1):
        model = None
        if args.sdk_ping:
            model, result, error = ping_id(handler, servo_id)
            ok = result == 0 and error == 0
            if result is None:
                if args.debug_errors:
                    print(
                        f"{family} {baud} ID {servo_id}: ignored malformed response",
                        file=sys.stderr,
                    )
                ok = False
        else:
            ok = raw_ping_id(port_handler, servo_id)

        if ok:
            found.append((servo_id, model, family, baud))
            if args.verbose and model is not None:
                print(f"{servo_id} model={model} family={family} baud={baud}")
            elif args.verbose:
                print(f"{servo_id} family={family} baud={baud}")
            else:
                print(servo_id)
            sys.stdout.flush()
        if not args.quiet and (offset % 25 == 0 or offset == total):
            print(
                f"scanned {offset}/{total}, found {len(found)}",
                file=sys.stderr,
                flush=True,
            )
    return found


def main():
    args = parse_args()
    if not args.port:
        raise SystemExit("--port is required, or set SERIAL_PORT")
    require_id("--start-id", args.start_id)
    require_id("--end-id", args.end_id)
    if args.start_id > args.end_id:
        raise SystemExit("--start-id must be less than or equal to --end-id")
    if args.baud <= 0:
        raise SystemExit("--baud must be positive")

    sdk = load_sdk()
    if args.sdk_ping:
        families = ("scscl", "sms_sts") if args.auto or args.family == "both" else (args.family,)
    else:
        families = ("raw",)
    bauds = AUTO_BAUDS if args.auto else (args.baud,)
    found = []
    port_handler = None

    try:
        for baud in bauds:
            port_handler = sdk.PortHandler(args.port)
            patch_pyserial_write(port_handler)
            try:
                if not port_handler.setBaudRate(baud):
                    if not args.quiet:
                        print(
                            f"skipping unsupported baud {baud}",
                            file=sys.stderr,
                            flush=True,
                        )
                    continue
                for family in families:
                    handler = make_handler(sdk, family, port_handler) if args.sdk_ping else None
                    found.extend(scan_bus(args, port_handler, handler, family, baud))
            finally:
                if port_handler.is_open:
                    port_handler.closePort()

        if not args.quiet and not found:
            print("no servos found", file=sys.stderr)
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
