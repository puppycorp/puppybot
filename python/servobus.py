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


def default_baud():
    env_baud = os.environ.get("BAUD")
    if not env_baud:
        return DEFAULT_BAUD
    try:
        return int(env_baud)
    except ValueError:
        raise SystemExit("BAUD must be an integer")


def add_bus_args(parser, family=True, family_required=False):
    parser.add_argument(
        "--port",
        default=os.environ.get("SERIAL_PORT"),
        help="Serial adapter path, e.g. /dev/tty.usbserial-1234 or COM3.",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=default_baud(),
        help=f"Serial baud rate. Defaults to BAUD or {DEFAULT_BAUD}.",
    )
    if family:
        parser.add_argument(
            "--family",
            choices=("sms_sts", "scscl"),
            required=family_required,
            help="Servo family: sms_sts for ST3215/ST3020, scscl for SC09/SC15.",
        )


def parse_args():
    parser = argparse.ArgumentParser(description="Work with STServo/SCServo serial bus servos.")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Print responding servo IDs.")
    add_bus_args(scan, family=False)
    scan.add_argument("--start-id", type=int, default=MIN_SERVO_ID)
    scan.add_argument("--end-id", type=int, default=MAX_SERVO_ID)
    scan.add_argument(
        "--family",
        choices=("sms_sts", "scscl", "both"),
        default="sms_sts",
        help="Used only with --sdk-ping. Raw ping is family-neutral.",
    )
    scan.add_argument("--auto", action="store_true", help="Try common baud rates.")
    scan.add_argument("--verbose", action="store_true", help="Print family/baud/model metadata.")
    scan.add_argument("--quiet", action="store_true", help="Do not print progress to stderr.")
    scan.add_argument("--debug-errors", action="store_true", help="Print per-ID parser errors.")
    scan.add_argument("--sdk-ping", action="store_true", help="Use SDK ping instead of raw ping.")

    assign = sub.add_parser("assign-id", help="Write a new ID to one connected servo.")
    add_bus_args(assign, family_required=True)
    assign.add_argument("--old-id", type=int, required=True)
    assign.add_argument("--new-id", type=int, required=True)
    assign.add_argument("--force", action="store_true", help="Allow writing when new ID already responds.")
    assign.add_argument("--skip-verify", action="store_true", help="Do not verify new ID after writing.")
    assign.add_argument("--ignore-status-errors", action="store_true", help="Continue when the servo reports status warnings.")

    move = sub.add_parser("move", help="Move a servo to a raw position.")
    add_bus_args(move, family_required=True)
    move.add_argument("--id", type=int, required=True)
    move.add_argument("--position", type=int, required=True, help="Raw target position.")
    move.add_argument("--speed", type=int, default=None, help="Raw moving speed.")
    move.add_argument("--time", type=int, default=0, help="SCSCL move time.")
    move.add_argument("--acc", type=int, default=50, help="SMS_STS acceleration.")
    move.add_argument("--no-check", action="store_true", help="Do not ping before moving.")
    move.add_argument("--ignore-status-errors", action="store_true", help="Continue when the servo reports status warnings.")

    wheel = sub.add_parser("wheel", help="Run a servo in continuous rotation mode.")
    add_bus_args(wheel, family_required=True)
    wheel.add_argument("--id", type=int, required=True)
    wheel.add_argument("--speed", type=int, required=True, help="Signed raw speed. Use 0 to stop.")
    wheel.add_argument("--acc", type=int, default=50, help="SMS_STS acceleration.")
    wheel.add_argument("--no-check", action="store_true", help="Do not ping before rotating.")
    wheel.add_argument("--ignore-status-errors", action="store_true", help="Continue when the servo reports status warnings.")

    mode = sub.add_parser("mode", help="Set servo operating mode.")
    add_bus_args(mode, family_required=True)
    mode.add_argument("--id", type=int, required=True)
    mode.add_argument("--mode", choices=("position", "wheel"), required=True)
    mode.add_argument("--min-position", type=int, default=0, help="SCSCL position mode minimum angle limit.")
    mode.add_argument("--max-position", type=int, default=1000, help="SCSCL position mode maximum angle limit.")
    mode.add_argument("--no-check", action="store_true", help="Do not ping before setting mode.")
    mode.add_argument("--ignore-status-errors", action="store_true", help="Continue when the servo reports status warnings.")

    status = sub.add_parser("status", help="Read basic status registers.")
    add_bus_args(status, family_required=True)
    status.add_argument("--id", type=int, required=True)

    return parser.parse_args()


def require_id(name, value):
    if value < MIN_SERVO_ID or value > MAX_SERVO_ID:
        raise SystemExit(f"{name} must be between {MIN_SERVO_ID} and {MAX_SERVO_ID}")


def require_bus_args(args):
    if args.baud <= 0:
        raise SystemExit("--baud must be positive")


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


def open_port(sdk, port, baud):
    port_handler = sdk.PortHandler(port)
    patch_pyserial_write(port_handler)
    try:
        if not port_handler.setBaudRate(baud):
            if port_handler.is_open:
                port_handler.closePort()
            return None
    except Exception:
        if port_handler.is_open:
            port_handler.closePort()
        return None
    return port_handler


def serial_candidates():
    try:
        from serial.tools import list_ports
    except ModuleNotFoundError:
        return []

    ports = list(list_ports.comports())
    if sys.platform == "darwin":
        preferred = [p for p in ports if p.device.startswith("/dev/cu.")]
    else:
        preferred = ports

    def is_noise(port):
        text = " ".join(
            str(value)
            for value in (port.device, port.name, port.description, port.manufacturer)
            if value
        ).lower()
        return "bluetooth" in text or "debug-console" in text

    useful = []
    for port in preferred:
        text = " ".join(
            str(value)
            for value in (port.device, port.name, port.description, port.manufacturer)
            if value
        ).lower()
        if is_noise(port):
            continue
        if port.vid is not None or "usb" in text or "wch" in text or "ch340" in text or "serial" in text:
            useful.append(port.device)

    if useful:
        return sorted(dict.fromkeys(useful))

    return sorted(dict.fromkeys(p.device for p in preferred if not is_noise(p)))


def ports_to_try(args):
    if args.port:
        return [args.port]
    ports = serial_candidates()
    if not ports:
        raise RuntimeError("no serial ports found; pass --port explicitly")
    return ports


def find_port_for_id(args, sdk, servo_id):
    ports = ports_to_try(args)
    if args.port:
        return args.port
    for port in ports:
        port_handler = open_port(sdk, port, args.baud)
        if port_handler is None:
            continue
        try:
            if raw_ping(port_handler, servo_id):
                print(f"using port {port}", file=sys.stderr)
                return port
        finally:
            if port_handler.is_open:
                port_handler.closePort()
    raise RuntimeError(f"could not find ID {servo_id} on any serial port at {args.baud} baud")


def checksum(packet):
    return (~(sum(packet[2:]) & 0xFF)) & 0xFF


def raw_ping(port_handler, servo_id, timeout_ms=80):
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
            if frame[-1] == checksum(frame[:-1]):
                return True
    return False


def result_message(handler, result, error):
    if result != 0:
        return handler.getTxRxResult(result)
    if error != 0:
        return handler.getRxPacketError(error)
    return "ok"


def check_result(handler, action, result, error, ignore_status_errors=False):
    if result != 0:
        raise RuntimeError(f"{action} failed: {result_message(handler, result, error)}")
    if error != 0:
        message = result_message(handler, result, error)
        if ignore_status_errors:
            print(f"warning: {action}: {message}", file=sys.stderr)
            return
        raise RuntimeError(f"{action} failed: {message}")


def sdk_ping(handler, servo_id):
    try:
        model, result, error = handler.ping(servo_id)
    except (IndexError, ValueError, TypeError):
        return None, None, None
    return model, result, error


def scan_bus(args, sdk, port, baud):
    port_handler = open_port(sdk, port, baud)
    if port_handler is None:
        if not args.quiet:
            print(f"skipping {port} at unsupported/unavailable baud {baud}", file=sys.stderr, flush=True)
        return []

    found = []
    families = ("scscl", "sms_sts") if args.sdk_ping and args.family == "both" else (args.family,)
    if not args.sdk_ping:
        families = ("raw",)

    try:
        for family in families:
            handler = make_handler(sdk, family, port_handler)[0] if args.sdk_ping else None
            mode = family if args.sdk_ping else "raw"
            total = args.end_id - args.start_id + 1
            if not args.quiet:
                print(
                    f"scanning IDs {args.start_id}..{args.end_id} on {port} "
                    f"at {baud} baud using {mode}",
                    file=sys.stderr,
                    flush=True,
                )
            for offset, servo_id in enumerate(range(args.start_id, args.end_id + 1), 1):
                model = None
                if args.sdk_ping:
                    model, result, error = sdk_ping(handler, servo_id)
                    ok = result == 0 and error == 0
                    if result is None and args.debug_errors:
                        print(f"{family} {baud} ID {servo_id}: malformed response", file=sys.stderr)
                else:
                    ok = raw_ping(port_handler, servo_id)
                if ok:
                    found.append((servo_id, model, family, baud))
                    if args.verbose and model is not None:
                        print(f"{servo_id} model={model} family={family} baud={baud} port={port}")
                    elif args.verbose:
                        print(f"{servo_id} family={family} baud={baud} port={port}")
                    else:
                        print(servo_id)
                    sys.stdout.flush()
                if not args.quiet and (offset % 25 == 0 or offset == total):
                    print(f"scanned {offset}/{total}, found {len(found)}", file=sys.stderr, flush=True)
    finally:
        if port_handler.is_open:
            port_handler.closePort()
    return found


def command_scan(args):
    require_bus_args(args)
    require_id("--start-id", args.start_id)
    require_id("--end-id", args.end_id)
    if args.start_id > args.end_id:
        raise SystemExit("--start-id must be less than or equal to --end-id")

    sdk = load_sdk()
    bauds = AUTO_BAUDS if args.auto else (args.baud,)
    ports = ports_to_try(args)
    found = []
    if not args.port and not args.quiet:
        print(f"trying ports: {', '.join(ports)}", file=sys.stderr)
    for port in ports:
        for baud in bauds:
            found.extend(scan_bus(args, sdk, port, baud))
    if not args.quiet and not found:
        print("no servos found", file=sys.stderr)
    return 0


def command_assign_id(args):
    require_bus_args(args)
    require_id("--old-id", args.old_id)
    require_id("--new-id", args.new_id)
    if args.old_id == args.new_id:
        raise SystemExit("--old-id and --new-id must differ")

    sdk = load_sdk()
    args.port = find_port_for_id(args, sdk, args.old_id)
    port_handler = open_port(sdk, args.port, args.baud)
    if port_handler is None:
        raise RuntimeError(f"failed to open {args.port} at {args.baud}")
    handler, id_register = make_handler(sdk, args.family, port_handler)
    try:
        if not raw_ping(port_handler, args.old_id):
            raise RuntimeError(f"old ID {args.old_id} did not respond")
        print(f"old ID {args.old_id} responded")

        if raw_ping(port_handler, args.new_id) and not args.force:
            raise RuntimeError(
                f"new ID {args.new_id} already responds; "
                "use --force only when you are sure one servo is connected"
            )

        result, error = handler.unLockEprom(args.old_id)
        check_result(handler, f"unlock EEPROM on ID {args.old_id}", result, error, args.ignore_status_errors)
        result, error = handler.write1ByteTxRx(args.old_id, id_register, args.new_id)
        check_result(handler, f"write new ID {args.new_id}", result, error, args.ignore_status_errors)
        time.sleep(0.1)

        for servo_id in (args.new_id, args.old_id):
            result, error = handler.LockEprom(servo_id)
            if result == 0 and error == 0:
                print(f"EEPROM locked via ID {servo_id}")
                break
        else:
            print("warning: ID changed, but EEPROM lock command did not get a reply")

        if not args.skip_verify:
            if not raw_ping(port_handler, args.new_id):
                raise RuntimeError(f"new ID {args.new_id} did not respond")
            print(f"new ID {args.new_id} responded")
        print(f"changed servo ID {args.old_id} -> {args.new_id}")
        return 0
    finally:
        if port_handler.is_open:
            port_handler.closePort()


def command_move(args):
    require_bus_args(args)
    require_id("--id", args.id)
    sdk = load_sdk()
    args.port = find_port_for_id(args, sdk, args.id)
    port_handler = open_port(sdk, args.port, args.baud)
    if port_handler is None:
        raise RuntimeError(f"failed to open {args.port} at {args.baud}")
    handler, _ = make_handler(sdk, args.family, port_handler)
    try:
        if not args.no_check and not raw_ping(port_handler, args.id):
            raise RuntimeError(f"ID {args.id} did not respond")
        if args.family == "sms_sts":
            speed = 2400 if args.speed is None else args.speed
            result, error = handler.WritePosEx(args.id, args.position, speed, args.acc)
        else:
            speed = 1000 if args.speed is None else args.speed
            result, error = handler.WritePos(args.id, args.position, args.time, speed)
        check_result(handler, f"move ID {args.id}", result, error, args.ignore_status_errors)
        print(f"moved ID {args.id} to position {args.position}")
        return 0
    finally:
        if port_handler.is_open:
            port_handler.closePort()


def command_wheel(args):
    require_bus_args(args)
    require_id("--id", args.id)
    sdk = load_sdk()
    args.port = find_port_for_id(args, sdk, args.id)
    port_handler = open_port(sdk, args.port, args.baud)
    if port_handler is None:
        raise RuntimeError(f"failed to open {args.port} at {args.baud}")
    handler, _ = make_handler(sdk, args.family, port_handler)
    try:
        if not args.no_check and not raw_ping(port_handler, args.id):
            raise RuntimeError(f"ID {args.id} did not respond")
        if args.family == "sms_sts":
            result, error = handler.WheelMode(args.id)
            check_result(handler, f"set wheel mode on ID {args.id}", result, error, args.ignore_status_errors)
            result, error = handler.WriteSpec(args.id, args.speed, args.acc)
        else:
            result, error = handler.PWMMode(args.id)
            check_result(handler, f"set PWM mode on ID {args.id}", result, error, args.ignore_status_errors)
            result, error = handler.WritePWM(args.id, args.speed)
        check_result(handler, f"rotate ID {args.id}", result, error, args.ignore_status_errors)
        print(f"rotating ID {args.id} at speed {args.speed}")
        return 0
    finally:
        if port_handler.is_open:
            port_handler.closePort()


def command_mode(args):
    require_bus_args(args)
    require_id("--id", args.id)
    sdk = load_sdk()
    args.port = find_port_for_id(args, sdk, args.id)
    port_handler = open_port(sdk, args.port, args.baud)
    if port_handler is None:
        raise RuntimeError(f"failed to open {args.port} at {args.baud}")
    handler, _ = make_handler(sdk, args.family, port_handler)
    try:
        if not args.no_check and not raw_ping(port_handler, args.id):
            raise RuntimeError(f"ID {args.id} did not respond")
        if args.family == "sms_sts":
            mode_value = 0 if args.mode == "position" else 1
            result, error = handler.write1ByteTxRx(args.id, sdk.SMS_STS_MODE, mode_value)
            check_result(handler, f"set {args.mode} mode on ID {args.id}", result, error, args.ignore_status_errors)
        elif args.mode == "wheel":
            result, error = handler.PWMMode(args.id)
            check_result(handler, f"set wheel mode on ID {args.id}", result, error, args.ignore_status_errors)
        else:
            if args.min_position < 0 or args.min_position > 1023:
                raise SystemExit("--min-position must be between 0 and 1023")
            if args.max_position < 0 or args.max_position > 1023:
                raise SystemExit("--max-position must be between 0 and 1023")
            if args.min_position >= args.max_position:
                raise SystemExit("--min-position must be less than --max-position")
            params = [
                handler.scs_lobyte(args.min_position),
                handler.scs_hibyte(args.min_position),
                handler.scs_lobyte(args.max_position),
                handler.scs_hibyte(args.max_position),
            ]
            result, error = handler.writeTxRx(args.id, sdk.SCSCL_MIN_ANGLE_LIMIT_L, len(params), params)
            check_result(handler, f"set position mode on ID {args.id}", result, error, args.ignore_status_errors)
        print(f"set ID {args.id} to {args.mode} mode")
        return 0
    finally:
        if port_handler.is_open:
            port_handler.closePort()


def command_status(args):
    require_bus_args(args)
    require_id("--id", args.id)
    sdk = load_sdk()
    args.port = find_port_for_id(args, sdk, args.id)
    port_handler = open_port(sdk, args.port, args.baud)
    if port_handler is None:
        raise RuntimeError(f"failed to open {args.port} at {args.baud}")
    handler, _ = make_handler(sdk, args.family, port_handler)
    try:
        if not raw_ping(port_handler, args.id):
            raise RuntimeError(f"ID {args.id} did not respond")

        voltage, voltage_result, voltage_error = handler.read1ByteTxRx(args.id, 62)
        temperature, temp_result, temp_error = handler.read1ByteTxRx(args.id, 63)

        print(f"id={args.id}")
        print(f"port={args.port}")
        print(f"family={args.family}")
        if voltage_result == 0:
            print(f"voltage_raw={voltage}")
            print(f"voltage_v={voltage / 10.0:.1f}")
            if voltage_error:
                print(f"voltage_status={handler.getRxPacketError(voltage_error)}")
        else:
            print(f"voltage_error={handler.getTxRxResult(voltage_result)}")
        if temp_result == 0:
            print(f"temperature_c={temperature}")
            if temp_error:
                print(f"temperature_status={handler.getRxPacketError(temp_error)}")
        else:
            print(f"temperature_error={handler.getTxRxResult(temp_result)}")
        return 0
    finally:
        if port_handler.is_open:
            port_handler.closePort()


def main():
    args = parse_args()
    try:
        if args.command == "scan":
            return command_scan(args)
        if args.command == "assign-id":
            return command_assign_id(args)
        if args.command == "move":
            return command_move(args)
        if args.command == "wheel":
            return command_wheel(args)
        if args.command == "mode":
            return command_mode(args)
        if args.command == "status":
            return command_status(args)
        raise AssertionError(f"unknown command: {args.command}")
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
