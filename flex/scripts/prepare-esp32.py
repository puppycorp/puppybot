#!/usr/bin/env python3
"""Embed a reviewed v1 physical configuration; no device I/O."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]


def word(value):
    return f'0x{struct.unpack("<Q", struct.pack("<d", value))[0]:016x}'


def prepare(source, output):
    raw = source.read_bytes()
    config = json.loads(raw)
    assert config['version'] == 1
    serial = config['serial'].encode('ascii')
    assert 0 < len(serial) <= 32 and all(32 <= byte <= 126 for byte in serial)
    lines = [f'// Configuration SHA256: {hashlib.sha256(raw).hexdigest()}',
             'fn pf_physical_config(config) {', '    pb_config_default(config);',
             '    pb_zero(config + 8, 32);',
             f'    pb_copy(config + 8, {json.dumps(config["serial"])}, {len(serial)});']
    drive = config['drive']
    for index, key in enumerate(('left_motor_id', 'right_motor_id', 'steering_servo_id',
                                 'steering_center_deg', 'steering_range_deg', 'command_timeout_ms')):
        value = drive[key]
        assert isinstance(value, int)
        lines.append(f'    pb_vset(config + 40, {index}, {value});')
    coordinate = config['coordinate']
    for index, key in enumerate(('forward_sign', 'left_sign', 'up_sign', 'base_yaw_offset_deg',
                                 'tcp_forward_sign', 'tcp_left_sign', 'tcp_up_sign')):
        value = coordinate[key]
        if index == 3:
            assert math.isfinite(value)
            value = word(value)
        else:
            assert value in (-1, 1)
        lines.append(f'    pb_vset(config + 128, {index}, {value});')
    joints = config['arm']['joints']
    assert len(joints) == 4
    for index, joint in enumerate(joints):
        values = [joint[key] for key in ('servo_id', 'tick_min', 'tick_max', 'reference_tick')]
        assert all(isinstance(value, int) for value in values)
        assert math.isfinite(joint['reference_angle_deg'])
        values += [word(math.radians(joint['reference_angle_deg'])), joint['angle_sign'], joint['drive_sign']]
        lines.append(f'    pb_config_set_joint(pb_config_joint(config, {index}), '+', '.join(map(str, values))+');')
        assert isinstance(joint['limit_enabled'], bool)
        lines.append(f'    pb_vset(pb_config_joint(config, {index}), 7, {int(joint["limit_enabled"])});')
    lines.append('    return pb_config_validate(config);\n}\n')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(lines))
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'puppybot.json')
    parser.add_argument('--output', type=Path, default=ROOT/'build/flex/esp32/config.flex')
    args = parser.parse_args()
    prepare(args.config, args.output)


if __name__ == '__main__':
    main()
