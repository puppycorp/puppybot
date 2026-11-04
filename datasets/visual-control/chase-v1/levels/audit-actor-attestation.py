#!/usr/bin/env python3
"""Check a staged exact actor-buffer journal against a recorded chase game.

Usage: audit-actor-attestation.py ACTOR_ATTESTATION_BIN GAME_DIR

The journal writer is not yet integrated into the active control path. This
checks internal bytes and game consistency only; it does not prove OS argv,
loaded libraries, that the model produced the logged output, or that the
journal was captured by the real run rather than fabricated afterwards.
"""
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np


def read_exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise ValueError('truncated actor attestation')
    return data


def audit(path, game):
    result = json.loads((game / 'result.json').read_text())
    initial = json.loads((game / 'initial.json').read_text())
    with (game / 'decisions.jsonl').open() as stream:
        rows = [json.loads(line) for line in stream]
    forbidden = ('straightBiasHundredths', 'straightAfterSteps', 'sampledActions', 'ensembleMembers',
                 'ensembleUntilSteps', 'actionNoisePercent', 'noisySteps', 'selfImitationKeepSteps',
                 'selfImitationRows', 'doorPass', 'doorEarly')
    if (result.get('game') != 'fetch' or result.get('controller') != 'native neural policy'
            or result.get('blackout') is not False or result.get('carryCue') is not True
            or result.get('farBricks') is not False or result.get('exploreTeacher') is not False
            or result.get('sweepTeacher') is not False or result.get('suppliedMap') is not False
            or result.get('taskEventHint') is not False or result.get('maximumBrickDistanceM') != 0.35
            or any(name in result for name in forbidden)):
        raise ValueError('game used an unsupported or recorded non-default actor mode')
    with path.open('rb') as stream:
        magic, version, seed, horizon, image_bytes, width, record_bytes = struct.unpack('<8s6q', read_exact(stream, 56))
        if (magic != b'PBATST01' or version != 1 or seed != result.get('seed') or horizon != result.get('steps')
                or horizon != len(rows) or not 1 <= horizon <= 512 or image_bytes not in (21168, 49152) or width not in (128, 256)):
            raise ValueError('invalid actor attestation header or game identity')
        input_bytes = (image_bytes + 7 + width) * 4
        output_bytes = (2 + width) * 4
        if record_bytes != 24 + image_bytes + input_bytes + output_bytes + 8:
            raise ValueError('invalid actor attestation record size')
        normalization = np.array([np.float32(i / 255.0) for i in range(256)], dtype='<f4').view('<u4')
        previous_action = b'\0' * 8
        previous_memory = b'\0' * (width * 4)
        last_sequence = last_frame = -1
        for index, row in enumerate(rows):
            actual_index, sequence, frame = struct.unpack('<3q', read_exact(stream, 24))
            image = read_exact(stream, image_bytes)
            inputs = read_exact(stream, input_bytes)
            output = read_exact(stream, output_bytes)
            action = read_exact(stream, 8)
            if (actual_index != index or sequence <= last_sequence or frame <= last_frame
                    or sequence + 1 != row.get('sequence') or frame + 10 != row['state']['totalSteps']):
                raise ValueError(f'wrong actor sequence or frame at step {index}')
            if index == 0 and frame != initial.get('totalSteps'):
                raise ValueError('initial actor frame differs from reset')
            last_sequence, last_frame = sequence, frame
            pixels = np.frombuffer(image, dtype=np.uint8)
            normalized = np.frombuffer(inputs, dtype='<u4', count=image_bytes)
            if not np.array_equal(normalized, normalization[pixels]):
                raise ValueError(f'actor image normalization mismatch at step {index}')
            feedback_offset = image_bytes * 4
            feedback = np.frombuffer(inputs, dtype='<f4', count=7, offset=feedback_offset)
            if not np.isfinite(feedback).all() or inputs[feedback_offset:feedback_offset + 8] != previous_action:
                raise ValueError(f'invalid feedback or previous action at step {index}')
            state = initial if index == 0 else rows[index - 1]['state']
            drive = state['controller']['drive']
            contact = 0.0
            if index:
                previous_feedback = rows[index - 1].get('proprio')
                if not isinstance(previous_feedback, list) or len(previous_feedback) != 7 or previous_feedback[5] not in (0.0, 1.0):
                    raise ValueError(f'missing or invalid prior proprioception at step {index}')
                contact = previous_feedback[5]
            expected_feedback = previous_action + struct.pack('<4f', drive['leftSpeed'] / 100.0,
                                                               drive['rightSpeed'] / 100.0,
                                                               (drive['steeringAngleDeg'] - 90) / 45.0, contact)
            if index and struct.pack('<6f', *previous_feedback[:6]) != expected_feedback:
                raise ValueError(f'prior proprioception differs from recorded drive state at step {index}')
            if inputs[feedback_offset:feedback_offset + 24] != expected_feedback:
                raise ValueError(f'feedback differs from preceding observed state at step {index}')
            phase = 'search' if index == 0 else rows[index - 1]['state']['findReturn']['phase']
            if phase not in ('search', 'return', 'delivered') or feedback[6] != (1.0 if phase == 'return' else 0.0):
                raise ValueError(f'nonstandard carry cue at step {index}')
            memory = inputs[feedback_offset + 28:]
            if memory != previous_memory:
                raise ValueError(f'recurrent memory does not match previous output at step {index}')
            values = np.frombuffer(output, dtype='<f4')
            if not np.isfinite(values).all() or np.any(np.abs(values[:2]) > 1.0) or action != output[:8]:
                raise ValueError(f'invalid or modified policy action at step {index}')
            recorded = row.get('action')
            if not isinstance(recorded, list) or len(recorded) != 2 or struct.pack('<2f', *recorded) != action:
                raise ValueError(f'applied action differs from recorded policy output at step {index}')
            previous_action, previous_memory = action, output[8:]
        footer, count = struct.unpack('<8sq', read_exact(stream, 16))
        if footer != b'PBDONE01' or count != horizon or stream.read(1):
            raise ValueError('missing, incorrect or trailing attestation footer')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return {'status': 'actor_journal_internally_consistent', 'seed': seed, 'steps': horizon,
            'actorJournalSHA256': h.hexdigest(), 'imageBytes': image_bytes, 'memoryWidth': width,
            'scope': 'bytes and game consistency only; aggregated contact header, argv, runtime identity, camera authenticity, policy replay and real robot behavior not independently established'}


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print(json.dumps(audit(Path(sys.argv[1]), Path(sys.argv[2])), sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, OverflowError, struct.error, json.JSONDecodeError) as error:
        raise SystemExit(f'Invalid actor attestation: {error}')
