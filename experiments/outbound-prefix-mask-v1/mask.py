#!/usr/bin/env python3
"""Create a new whole-episode PVDATA04 aggregate with teacher outbound labels.

The input aggregate must be a 300-step, burn-in-zero map-aggregate in the
listed shard order. Original files are never modified. This tool does not
qualify data for training, prove teacher quality, or run a trainer.
"""
import argparse
import hashlib
import json
import math
import mmap
import os
import shutil
import struct
from pathlib import Path

HORIZON = 300
IMAGE = 21168
RAW_ROW = 44
AGG_ROW = 56
MAP_ROW = 144
GIB = 1024 ** 3
ONE = struct.pack('<f', 1.0)
ZERO = b'\0' * 4


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def header(data, magic, width):
    if len(data) < 32 or data[:8] != magic:
        raise ValueError('invalid dataset magic')
    count, fit, length = struct.unpack_from('<3q', data, 8)
    if not (2 <= count <= 1024 and 1 <= fit < count and length == HORIZON and
            len(data) == 32 + count * length * width):
        raise ValueError('invalid whole-episode dataset dimensions')
    return count, fit


def decisions(path, result, initial, events, source, episode, seed):
    result = json.loads(Path(result).read_text())
    if (result.get('steps') != HORIZON or result.get('game') != 'fetch' or
            result.get('controller') != 'exploring fetch teacher' or result.get('exploreTeacher') is not True or
            type(result.get('seed')) is not int or result['seed'] != seed):
        raise ValueError('teacher result does not describe a complete exploring-teacher game')
    initial = json.loads(Path(initial).read_text())
    if initial.get('findReturn', {}).get('consumedIndex') != -1:
        raise ValueError('teacher game does not begin in an unconsumed state')
    with Path(events).open() as stream:
        event_rows = [json.loads(line) for line in stream]
    if (not event_rows or event_rows[0].get('event') != 'start' or
            any(event.get('event') != 'delivery' for event in event_rows[1:])):
        raise ValueError('invalid teacher event sequence')
    deliveries = [event.get('step') for event in event_rows[1:]]
    if (type(result.get('deliveries')) is not int or len(deliveries) != result['deliveries'] or
            any(type(step) is not int or not 0 < step <= HORIZON for step in deliveries) or
            deliveries != sorted(set(deliveries))):
        raise ValueError('teacher delivery events disagree with result')
    with Path(path).open() as stream:
        rows = [json.loads(line) for line in stream]
    if len(rows) != HORIZON:
        raise ValueError('teacher decisions are incomplete')
    first = None
    base = 32 + episode * HORIZON * (IMAGE + RAW_ROW) + HORIZON * IMAGE
    for index, row in enumerate(rows):
        state = row.get('state', {}).get('findReturn', {})
        consumed = state.get('consumedIndex')
        phase = state.get('phase'); delivered = state.get('deliveries')
        action = row.get('action')
        if (type(consumed) is not int or consumed < -1 or not isinstance(action, list) or
                phase not in ('search', 'return', 'delivered', 'docked') or
                (phase == 'search') != (consumed < 0) or type(delivered) is not int or
                delivered != sum(step <= index + 1 for step in deliveries) or
                (phase == 'delivered') != (index + 1 in deliveries) or
                len(action) != 2 or not all(type(x) in (float, int) and math.isfinite(x) and abs(x) <= 1 for x in action)):
            raise ValueError('malformed teacher decision')
        offset = base + index * RAW_ROW
        if source[offset + 28:offset + 36] != struct.pack('<2f', *action):
            raise ValueError('teacher action differs from recorded data')
        if first is None and consumed >= 0:
            first = index + 1  # decision state is post-action; include that action
    if type(result.get('reaches')) is not int or (result['reaches'] > 0) != (first is not None):
        raise ValueError('teacher consumption states disagree with result')
    return first


def open_map(stack, path):
    stream = stack.enter_context(Path(path).open('rb'))
    return stack.enter_context(mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ))


def verify_output(data_path, output_map, merged, merged_map, selected, fitting):
    import contextlib
    with contextlib.ExitStack() as stack:
        output = open_map(stack, data_path)
        if header(output, b'PVDATA04', IMAGE + AGG_ROW) != (len(selected), fitting):
            raise ValueError('derived data header differs')
        maps = open_map(stack, output_map) if output_map is not None else None
        if maps is not None and header(maps, b'PVMAP001', MAP_ROW) != (len(selected), fitting):
            raise ValueError('derived map header differs')
        for target_index, (source_index, cutoff, _) in enumerate(selected):
            src = 32 + source_index * HORIZON * (IMAGE + AGG_ROW)
            dst = 32 + target_index * HORIZON * (IMAGE + AGG_ROW)
            if output[dst:dst + HORIZON * IMAGE] != merged[src:src + HORIZON * IMAGE]:
                raise ValueError('derived image history differs')
            for step in range(HORIZON):
                a = src + HORIZON * IMAGE + step * AGG_ROW
                b = dst + HORIZON * IMAGE + step * AGG_ROW
                expected_weight = ZERO if cutoff is not None and step >= cutoff else merged[a + 40:a + 44]
                if (output[b:b + 40] != merged[a:a + 40] or output[b + 40:b + 44] != expected_weight or
                        output[b + 44:b + AGG_ROW] != merged[a + 44:a + AGG_ROW]):
                    raise ValueError('derived supervision or recurrent feedback differs')
            if maps is not None:
                a = 32 + source_index * HORIZON * MAP_ROW
                b = 32 + target_index * HORIZON * MAP_ROW
                if maps[b:b + HORIZON * MAP_ROW] != merged_map[a:a + HORIZON * MAP_ROW]:
                    raise ValueError('derived map order differs')


def require_floor(path, min_free):
    if shutil.disk_usage(path).free < min_free:
        raise ValueError('free space fell below the required floor; output is incomplete')


def create(aggregate, shards, output, map_path=None, min_free=32 * GIB,
           teacher_selection=None):
    """Derive an aggregate; optional selections are caller-provided, not qualification.

    teacher_selection maps each teacher shard's absolute path to its source
    data/report hashes and exact fitting episode, seed and evidence hashes. An
    omitted teacher game, including every teacher validation game, is then
    excluded.  Callers must separately audit quality and data provenance.
    """
    import contextlib
    aggregate = Path(aggregate).absolute(); output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('output exists; preserve it')
    if not shards or not any(flag for _, flag in shards):
        raise ValueError('at least one explicit teacher shard is required')
    directories = [Path(directory).absolute() for directory, _ in shards]
    if len(set(directories)) != len(directories) or len({p.resolve() for p in directories}) != len(directories):
        raise ValueError('duplicate source shard')
    if teacher_selection is not None:
        teacher_paths = {str(Path(directory).absolute()) for directory, flag in shards if flag is True}
        if not isinstance(teacher_selection, dict) or set(teacher_selection) != teacher_paths:
            raise ValueError('selection must bind every teacher shard exactly once')
    # Writing an output under a source tree mutates its inventory even when
    # none of the existing files are overwritten. Resolve the parent links as
    # well so an apparently separate path cannot point back into a source.
    resolved_output = output.resolve()
    protected = [aggregate.parent.resolve()]
    protected.extend(Path(directory).absolute().resolve() for directory, _ in shards)
    if map_path is not None: protected.append(Path(map_path).absolute().parent.resolve())
    if any(resolved_output == path or resolved_output.is_relative_to(path) for path in protected):
        raise ValueError('output must not be inside an input tree')
    if aggregate.is_symlink() or not aggregate.is_file():
        raise ValueError('aggregate must be a regular file')
    inputs = {str(aggregate): sha(aggregate)}
    with contextlib.ExitStack() as stack:
        merged = open_map(stack, aggregate); total, fitting = header(merged, b'PVDATA04', IMAGE + AGG_ROW)
        merged_map = None
        if map_path is not None:
            map_path = Path(map_path).absolute()
            if map_path.is_symlink() or not map_path.is_file(): raise ValueError('invalid map input')
            inputs[str(map_path)] = sha(map_path)
            merged_map = open_map(stack, map_path)
            if header(merged_map, b'PVMAP001', MAP_ROW) != (total, fitting):
                raise ValueError('map and data split differs')
        sources = []
        for directory, mask_teacher in shards:
            directory = Path(directory).absolute()
            if type(mask_teacher) is not bool or directory.is_symlink() or not directory.is_dir():
                raise ValueError('invalid shard declaration')
            data_path = directory / 'data.bin'; report_path = directory / 'report.json'
            if any(path.is_symlink() or not path.is_file() for path in (data_path, report_path)):
                raise ValueError('invalid shard paths')
            report = json.loads(report_path.read_text()); data_hash = sha(data_path)
            if report.get('complete') is not True or report.get('dataSHA256') != data_hash:
                raise ValueError('incomplete or changed shard receipt')
            if mask_teacher:
                expected_teacher = {'studentDriven': False, 'teacher': 'exploring fetch teacher',
                    'teacherUsesCameraDetections': True, 'teacherUsesReferenceGeometryForWallsOnly': True,
                    'teacherUsesTargetCoordinates': False, 'actorUsesReferencePose': False,
                    'actorUsesTargetCoordinates': False}
                if any(type(report.get(key)) is not type(value) or report.get(key) != value
                       for key, value in expected_teacher.items()):
                    raise ValueError('teacher source declarations differ')
            raw = open_map(stack, data_path); count, fit = header(raw, b'PVDATA01', IMAGE + RAW_ROW)
            if (report.get('episodes') != count or report.get('trainingEpisodes') != fit or
                    report.get('sequenceLength') != HORIZON):
                raise ValueError('shard split differs from receipt')
            inputs[str(data_path)] = data_hash; inputs[str(report_path)] = sha(report_path)
            if type(report.get('seed')) is not int or report['seed'] < 0:
                raise ValueError('invalid shard seed')
            if mask_teacher and teacher_selection is not None:
                entry = teacher_selection[str(directory)]
                if (not isinstance(entry, dict) or set(entry) != {'dataSHA256', 'reportSHA256', 'episodes'} or
                        entry['dataSHA256'] != data_hash or entry['reportSHA256'] != inputs[str(report_path)] or
                        not isinstance(entry['episodes'], list)):
                    raise ValueError('teacher selection source identity differs')
                identities = []
                for item in entry['episodes']:
                    evidence = item.get('evidence') if isinstance(item, dict) else None
                    if (not isinstance(item, dict) or set(item) != {'episode', 'seed', 'evidence'} or
                            type(item['episode']) is not int or type(item['seed']) is not int or
                            not 0 <= item['episode'] < fit or item['seed'] != report['seed'] + item['episode'] or
                            not isinstance(evidence, dict) or
                            set(evidence) != {'result.json', 'initial.json', 'chase.jsonl', 'decisions.jsonl'} or
                            any(not isinstance(value, str) or len(value) != 64 or
                                any(char not in '0123456789abcdef' for char in value) for value in evidence.values())):
                        raise ValueError('teacher selection is not an exact fitting identity')
                    identities.append(item['episode'])
                if len(set(identities)) != len(identities):
                    raise ValueError('duplicate teacher episode selection')
            source_map = None
            if merged_map is not None:
                source_map_path = directory / 'map.bin'
                if source_map_path.is_symlink(): raise ValueError('symlinked shard map')
                if source_map_path.exists():
                    if not source_map_path.is_file(): raise ValueError('invalid shard map')
                    source_map_hash = sha(source_map_path)
                    if report.get('mapSHA256') != source_map_hash:
                        raise ValueError('shard map does not match its receipt')
                    inputs[str(source_map_path)] = source_map_hash
                    source_map = open_map(stack, source_map_path)
                    if header(source_map, b'PVMAP001', MAP_ROW) != (count, fit):
                        raise ValueError('shard map and data split differs')
                elif report.get('mapSHA256') not in (None, ''):
                    raise ValueError('shard receipt names a missing map')
            sources.append((directory, raw, count, fit, mask_teacher, report['seed'], source_map))
        order = [(directory, raw, index, mask_teacher, split == 0, seed + index, source_map)
                 for split in (0, 1) for directory, raw, count, fit, mask_teacher, seed, source_map in sources
                 for index in (range(fit) if split == 0 else range(fit, count))]
        if len(order) != total or sum(row[4] for row in order) != fitting:
            raise ValueError('aggregate and shard order or split differs')
        selected = []; excluded = []; stats = []
        for aggregate_index, (directory, raw, episode, mask_teacher, is_fit, seed, source_map) in enumerate(order):
            source_base = 32 + episode * HORIZON * (IMAGE + RAW_ROW)
            target_base = 32 + aggregate_index * HORIZON * (IMAGE + AGG_ROW)
            if merged[target_base:target_base + HORIZON * IMAGE] != raw[source_base:source_base + HORIZON * IMAGE]:
                raise ValueError('aggregate image history differs from source shard')
            if merged_map is not None:
                target_map = 32 + aggregate_index * HORIZON * MAP_ROW
                if source_map is None:
                    expected_map = b'\x02' * (HORIZON * MAP_ROW)
                else:
                    source_map_base = 32 + episode * HORIZON * MAP_ROW
                    expected_map = source_map[source_map_base:source_map_base + HORIZON * MAP_ROW]
                if merged_map[target_map:target_map + HORIZON * MAP_ROW] != expected_map:
                    raise ValueError('aggregate map history differs from source shard')
            cutoff = None
            if mask_teacher:
                run = directory / f'expert-{episode}'
                if (run.is_symlink() or not run.is_dir() or
                        run.resolve().parent != directory.resolve()):
                    raise ValueError('invalid or detached teacher episode directory')
                paths = [run / 'decisions.jsonl', run / 'result.json', run / 'initial.json', run / 'chase.jsonl']
                if any(path.is_symlink() or not path.is_file() or path.resolve().parent != run.resolve() for path in paths):
                    raise ValueError('missing or symlinked teacher evidence')
                inputs.update({str(path): sha(path) for path in paths})
                if mask_teacher and teacher_selection is not None:
                    matching = [item for item in teacher_selection[str(directory)]['episodes'] if item['episode'] == episode]
                    if matching and any(inputs[str(path)] != matching[0]['evidence'][path.name] for path in paths):
                        raise ValueError('selected teacher episode evidence changed')
                cutoff = decisions(*paths, raw, episode, seed)
            labels = 0
            for step in range(HORIZON):
                src = source_base + HORIZON * IMAGE + step * RAW_ROW
                dst = target_base + HORIZON * IMAGE + step * AGG_ROW
                weight = merged[dst + 40:dst + 44]
                if (merged[dst:dst + 40] != raw[src:src + 40] or
                        weight not in (ZERO, ONE) or raw[src + 40:src + 44] not in (ZERO, ONE) or
                        (weight == ONE and raw[src + 40:src + 44] != ONE) or
                        merged[dst + 44:dst + 48] != ONE or
                        merged[dst + 48:dst + 56] != raw[src + 28:src + 36]):
                    raise ValueError('aggregate row does not match source or valid-frame mask')
                if weight == ONE and (not mask_teacher or cutoff is not None and step < cutoff): labels += 1
            if mask_teacher and teacher_selection is not None:
                permitted = {item['episode'] for item in teacher_selection[str(directory)]['episodes']}
                if episode not in permitted:
                    excluded.append({'aggregateIndex': aggregate_index, 'shard': str(directory), 'episode': episode,
                                     'fit': is_fit, 'reason': 'not_selected_fitting_teacher'})
                    continue
                if cutoff is None:
                    raise ValueError('selected teacher episode has no consumption')
            if mask_teacher and cutoff is None:
                excluded.append({'aggregateIndex': aggregate_index, 'shard': str(directory), 'episode': episode, 'fit': is_fit})
                continue
            if labels == 0:
                raise ValueError('selected episode would create an empty-label batch')
            selected.append((aggregate_index, cutoff if mask_teacher else None, is_fit))
            stats.append({'aggregateIndex': aggregate_index, 'shard': str(directory), 'episode': episode,
                          'fit': is_fit, 'teacherPrefix': mask_teacher,
                          'firstConsumptionAction': cutoff, 'remainingLabels': labels})
        selected_fit = sum(row[2] for row in selected)
        if not (2 <= len(selected) <= 1024 and 1 <= selected_fit < len(selected)):
            raise ValueError('filter leaves an invalid fitting/validation split')
        teacher_fit = sum(row['fit'] and row['teacherPrefix'] for row in stats)
        teacher_fit_labels = sum(row['remainingLabels'] for row in stats if row['fit'] and row['teacherPrefix'])
        if not teacher_fit or not teacher_fit_labels:
            raise ValueError('no fitting teacher-prefix labels remain')
        required = 32 + len(selected) * HORIZON * (IMAGE + AGG_ROW)
        if merged_map is not None: required += 32 + len(selected) * HORIZON * MAP_ROW
        if shutil.disk_usage(output.parent).free < min_free + required:
            raise ValueError('insufficient disk for a separate output and free-space floor')
        if any(sha(path) != value for path, value in inputs.items()):
            raise ValueError('inputs changed before output creation')
        output.mkdir()
        data_output = output / 'data.bin'
        with data_output.open('xb') as dst:
            dst.write(b'PVDATA04' + struct.pack('<3q', len(selected), selected_fit, HORIZON))
            for index, cutoff, _ in selected:
                require_floor(output, min_free)
                base = 32 + index * HORIZON * (IMAGE + AGG_ROW)
                dst.write(merged[base:base + HORIZON * IMAGE])
                for step in range(HORIZON):
                    row = bytearray(merged[base + HORIZON * IMAGE + step * AGG_ROW:base + HORIZON * IMAGE + (step + 1) * AGG_ROW])
                    if cutoff is not None and step >= cutoff: row[40:44] = ZERO
                    dst.write(row)
                require_floor(output, min_free)
            dst.flush(); os.fsync(dst.fileno())
        if merged_map is not None:
            with (output / 'map.bin').open('xb') as dst:
                dst.write(b'PVMAP001' + struct.pack('<3q', len(selected), selected_fit, HORIZON))
                for index, _, _ in selected:
                    require_floor(output, min_free)
                    base = 32 + index * HORIZON * MAP_ROW
                    dst.write(merged_map[base:base + HORIZON * MAP_ROW])
                    require_floor(output, min_free)
                dst.flush(); os.fsync(dst.fileno())
        if any(sha(path) != value for path, value in inputs.items()):
            raise ValueError('inputs changed during output creation; output is incomplete')
        verify_output(data_output, output / 'map.bin' if merged_map is not None else None,
                      merged, merged_map, selected, selected_fit)
        require_floor(output, min_free)
        report = {'schema': 'puppybot.outbound-prefix-mask.v1', 'status': 'candidate_data_only',
                  'sourceFiles': inputs, 'sourceEpisodes': total, 'outputEpisodes': len(selected),
                  'outputFittingEpisodes': selected_fit, 'excludedTeacherEpisodes': excluded,
                  'fittingTeacherEpisodes': teacher_fit, 'fittingTeacherLabels': teacher_fit_labels,
                  'teacherSelection': teacher_selection,
                  'selectionQualityVerified': False, 'trainingAuthorized': False,
                  'episodes': stats, 'dataSHA256': sha(data_output),
                  'mapSHA256': sha(output / 'map.bin') if merged_map is not None else None,
                  'scope': 'saved post-action virtual consumption only; no training, held-out or physical claim'}
        partial_report = output / 'report.partial.json'
        with partial_report.open('x') as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
            stream.flush(); os.fsync(stream.fileno())
        require_floor(output, min_free)
        os.link(partial_report, output / 'report.json')
        partial_report.unlink()
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aggregate', required=True); parser.add_argument('--map')
    parser.add_argument('--output', required=True)
    parser.add_argument('--shard', action='append', nargs=2, metavar=('ROLE', 'DIRECTORY'), required=True,
                        help='ordered map-aggregate source: ROLE is teacher-prefix or preserve')
    args = parser.parse_args()
    if any(role not in ('teacher-prefix', 'preserve') for role, _ in args.shard):
        parser.error('invalid shard role')
    result = create(args.aggregate, [(path, role == 'teacher-prefix') for role, path in args.shard], args.output, args.map)
    print(json.dumps({'status': result['status'], 'outputEpisodes': result['outputEpisodes'],
                      'excludedTeacherEpisodes': len(result['excludedTeacherEpisodes'])}))


if __name__ == '__main__':
    main()
