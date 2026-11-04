#!/usr/bin/env python3
"""Check fixed paired batch journals and full training/validation orders."""
import hashlib
import struct
from pathlib import Path


SEED = 7120000
FITTING = 935
EPISODES = 1031
BATCH = 2
RECORDS = 468


def read_regular(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('journal or order must be a regular file')
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('journal or order changed while reading')
    return data


def decode_order(data):
    if len(data) != EPISODES * 8:
        raise ValueError('training order has wrong size')
    order = struct.unpack(f'<{EPISODES}Q', data)
    if set(order[:FITTING]) != set(range(FITTING)) or order[FITTING:] != tuple(range(FITTING, EPISODES)):
        raise ValueError('training order is not the fitting permutation and fixed validation split')
    return order


def decode_journal(data, order):
    if len(data) != 40 + RECORDS * 48 + 16:
        raise ValueError('batch journal has wrong size')
    if struct.unpack_from('<8s4q', data) != (b'PBMIRR01', 1, SEED, FITTING, BATCH):
        raise ValueError('batch journal header differs')
    if struct.unpack_from('<8sQ', data, len(data) - 16) != (b'PBDONE01', RECORDS):
        raise ValueError('batch journal footer differs')
    rng = (SEED ^ 0x5a5a5a5a) & 2147483647
    rows = []
    for index in range(RECORDS):
        number, start, count, mask, first, second = struct.unpack_from('<6q', data, 40 + index * 48)
        expected_start = index * BATCH
        expected_count = min(BATCH, FITTING - expected_start)
        if number != index or start != expected_start or count != expected_count:
            raise ValueError('batch index, start or count differs')
        expected_mask = 0
        for bit in range(expected_count):
            rng = (rng * 1103515245 + 12345) & 2147483647
            expected_mask |= ((rng >> 15) & 1) << bit
        expected_second = order[start + 1] if expected_count == 2 else -1
        if mask != expected_mask or first != order[start] or second != expected_second:
            raise ValueError('batch order, count, episode identity or mirror mask differs')
        rows.append((number, start, count, mask, first, second))
    return rows


def verify(control_journal, control_first_order, control_final_order,
           treatment_journal, treatment_first_order, treatment_final_order):
    paths = tuple(map(Path, (control_journal, control_first_order, control_final_order,
                             treatment_journal, treatment_first_order, treatment_final_order)))
    identities = [(path.stat().st_dev, path.stat().st_ino) for path in paths]
    if len(set(identities)) != len(paths):
        raise ValueError('paired journal or order files alias')
    cj, co, cf, tj, to, tf = map(read_regular, paths)
    if co != cf or to != tf:
        raise ValueError('first and final order differ within an arm')
    control = decode_order(co)
    treatment = decode_order(to)
    if control != treatment:
        raise ValueError('paired training orders differ')
    left = decode_journal(cj, control)
    right = decode_journal(tj, treatment)
    if left != right:
        raise ValueError('paired batch journals differ')
    return {'status': 'paired_batch_schedule_consistent', 'batches': len(left), 'fittingEpisodes': FITTING,
            'validationEpisodes': EPISODES - FITTING, 'lastBatchCount': left[-1][2],
            'controlJournalSHA256': hashlib.sha256(cj).hexdigest(),
            'treatmentJournalSHA256': hashlib.sha256(tj).hexdigest(),
            'orderSHA256': hashlib.sha256(co).hexdigest(),
            'scope': 'saved host batch metadata only; not GPU consumption, optimizer or execution attestation'}
