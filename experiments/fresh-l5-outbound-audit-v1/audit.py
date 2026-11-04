#!/usr/bin/env python3
"""Read-only post-hoc L5 outbound comparison of retained selection games."""
import collections
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
TASK = P / 'fresh-policy-selection-v2/L5'
MONITOR = P / 'fresh-policy-selection-monitored-v2'
REPORT = P / 'fresh-policy-selection-v2/report.json'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


retry = load('outbound_fresh_retry', ROOT / 'experiments/fresh-policy-comparison-v2/retry.py')
historic = load('outbound_previous_audit', ROOT / 'experiments/outbound-teacher-audit-v1/audit.py')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def bucket(student, teacher):
    if student is None and teacher is None: return 'both_missed'
    if student is None: return 'teacher_only'
    if teacher is None: return 'student_only'
    if teacher < student: return 'teacher_earlier'
    if student < teacher: return 'student_earlier'
    return 'tie'


def common_prefix(games, arm):
    if len(games) < 2: return None
    first = games[0]['arms'][arm]['path']
    return next((i for i in range(300) if any(game['arms'][arm]['path'][i] != first[i]
                                               for game in games[1:])), 300)


def summarize(games):
    counts = collections.Counter(bucket(g['arms']['control']['first'], g['arms']['teacher']['first'])
                                 for g in games)
    misses = [g for g in games if g['arms']['control']['first'] is None]
    rescued = [g for g in misses if g['arms']['teacher']['first'] is not None]
    misses_teacher = [g for g in games if g['arms']['teacher']['first'] is None]
    same_room = [g for g in rescued if g['layout'] == 13]
    teacher_room = [g for g in misses_teacher if g['layout'] == 15]
    both = [g for g in games if g['arms']['control']['first'] is not None and g['arms']['teacher']['first'] is not None]
    output = []
    for game in rescued:
        teacher = game['arms']['teacher']
        output.append({'seed': game['seed'], 'layout': game['layout'], 'variant': game['variant'],
                       'teacherFirstConsumption': teacher['first'], 'teacherDeliveries': teacher['deliveries'],
                       'teacherPreConsumptionBackForth': teacher['before'], 'teacherFullBackForth': teacher['all']})
    return {'buckets': dict(sorted(counts.items())), 'studentMisses': len(misses),
            'studentMissesTeacherFinds': len(rescued),
            'studentMissesTeacherFindsAndDelivers': sum(g['arms']['teacher']['deliveries'] > 0 for g in rescued),
            'bothConsumeTeacherAtLeast10ActionsEarlier': sum(g['arms']['control']['first'] - g['arms']['teacher']['first'] >= 10 for g in both),
            'bothConsumeStudentAtLeast10ActionsEarlier': sum(g['arms']['teacher']['first'] - g['arms']['control']['first'] >= 10 for g in both),
            'teacherMissSeeds': [g['seed'] for g in misses_teacher], 'studentMissTeacherFindCases': output,
            'correlatedPrefixes': {'layout13StudentMissCount': len(same_room),
                                   'layout13StudentActionPosePrefix': common_prefix(same_room, 'control'),
                                   'layout13TeacherActionPosePrefix': common_prefix(same_room, 'teacher'),
                                   'layout15TeacherMissCount': len(teacher_room),
                                   'layout15TeacherActionPosePrefix': common_prefix(teacher_room, 'teacher')}}


def audit():
    frozen = retry.verify()
    if json.loads((MONITOR / 'monitor-result.json').read_text()) != {'status': 'failed', 'reason': 'unsafe or vanished output directory'}:
        raise ValueError('original monitor status changed')
    if (MONITOR / 'completion.json').exists(): raise ValueError('unexpected completion receipt')
    saved = json.loads(REPORT.read_text())
    check = retry.base.auditor.audit_task('L5', TASK, TASK, retry.base.MODELS)
    if check.get('status') != 'complete_diagnostic': raise ValueError('L5 saved audit failed')
    prior = saved['tasks']['L5']
    without_longer = json.loads(json.dumps(prior))
    for arm in retry.base.MODELS: without_longer['results'][arm].pop('longerSearchLoops', None)
    if check != without_longer: raise ValueError('L5 report differs from saved game audit')
    for arm in ('control', 'treatment', 'teacher'):
        status = json.loads((P / 'fresh-policy-selection-v2/supervisors/L5' / arm / 'supervisor-result.json').read_text())
        if not retry.base.monitor.clean(status): raise ValueError('unclean L5 arm')
    games = []
    for i in range(32):
        seed = 7820000 + i
        task = frozen['design']['tasks'][4]
        design = task['rows'][i]
        if task['name'] != 'L5' or design['seed'] != seed: raise ValueError('unexpected frozen case')
        directories = {'control': TASK / 'control' / str(i // 8) / str(seed),
                       'teacher': TASK / 'teacher' / str(i // 8) / ('expert-' + str(i % 8))}
        arms = {}
        for arm, directory in directories.items():
            rows = [json.loads(line) for line in (directory / 'decisions.jsonl').open()]
            event = json.loads((directory / 'chase.jsonl').open().readline())
            result = json.loads((directory / 'result.json').read_text())
            first = historic.first_consumption(rows)
            marked = historic.reversal_marks(rows, event['robot'])
            if len(rows) != 300 or len(marked) != result['backForthSteps']:
                raise ValueError('saved reversal count differs')
            # Restrict windows to actions strictly before first consumption.
            before = len(historic.reversal_marks(rows[:first - 1], event['robot'])) if first else None
            arms[arm] = {'first': first, 'deliveries': result['deliveries'], 'before': before,
                         'all': len(marked), 'path': [(row['action'], row['state']['pose']) for row in rows]}
        games.append({'seed': seed, 'layout': design['layout'], 'variant': design['variant'], 'arms': arms})
    result = summarize(games)
    if sum(result['buckets'].values()) != 32 or retry.verify() != frozen:
        raise ValueError('incomplete games or frozen inputs changed')
    result.update({'status': 'posthoc_saved_selection_only', 'games': 32,
                   'reportSHA256': sha(REPORT), 'scriptSHA256': sha(Path(__file__)),
                   'scope': 'original monitor failed; no held-out, physical or execution attestation'})
    return result


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2, sort_keys=True, allow_nan=False))
