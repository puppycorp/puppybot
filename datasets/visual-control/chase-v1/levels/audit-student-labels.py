#!/usr/bin/env python3
"""Check saved student-driven shard labels against its decision journals.

Usage: audit-student-labels.py SHARD_DIR [SHARD_DIR ...]
This checks row weights, finite bounded labels and disagreement counts. It
does not prove that the teacher's labels are correct or unprivileged.
"""
import json
import math
import mmap
import struct
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    games = disagreements = 0
    for name in sys.argv[1:]:
        shard = Path(name)
        report = json.loads((shard / 'report.json').read_text())
        if report.get('complete') is not True or report.get('studentDriven') is not True:
            raise ValueError(f'not a completed student-driven shard: {shard}')
        n, horizon = report['episodes'], report['sequenceLength']
        with (shard / 'data.bin').open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            if data[:8] != b'PVDATA01' or struct.unpack_from('<q', data, 8)[0] != n or struct.unpack_from('<q', data, 24)[0] != horizon or horizon != 300 or len(data) != 32 + n * horizon * 21212:
                raise ValueError(f'invalid source data layout: {shard}')
            for episode in range(n):
                directory = shard / f'expert-{episode}'
                result = json.loads((directory / 'result.json').read_text())
                with (directory / 'decisions.jsonl').open() as decisions:
                    rows = [json.loads(line) for line in decisions]
                if len(rows) != horizon:
                    raise ValueError(f'incomplete decisions: {directory}')
                offset = 32 + episode * horizon * 21212 + horizon * 21168
                difference = 0
                for step, row in enumerate(rows):
                    action = struct.unpack_from('<2f', data, offset + step * 44 + 28)
                    weight = struct.unpack_from('<f', data, offset + step * 44 + 40)[0]
                    if not all(math.isfinite(x) and abs(x) <= 1 for x in action) or weight != 1:
                        raise ValueError(f'invalid or masked student-driven label: {directory}, step {step}')
                    difference += struct.pack('<2f', *action) != struct.pack('<2f', *row['action'])
                if difference != result['teacherDisagreements']:
                    raise ValueError(f'teacher-label disagreement count mismatch: {directory}')
                games += 1
                disagreements += difference
    if not disagreements:
        raise ValueError('no teacher/student action disagreements in the checked games')
    print(json.dumps({'status': 'passed', 'games': games, 'teacherStudentDisagreementSteps': disagreements,
                      'scope': 'saved row and journal consistency; not a teacher correctness audit'}, sort_keys=True))


if __name__ == '__main__':
    main()
