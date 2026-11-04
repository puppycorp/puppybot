#!/usr/bin/env python3
"""Create a screened outbound candidate while preserving baseline data."""
import fcntl
import importlib.util
import json
import os
import shutil
import struct
import types
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
BASE = P / 'search-dagger-l35-4workers/data'
PILOT = P / 'outbound-diverse-prefix-pilot-v1'
MONITOR = P / 'outbound-diverse-prefix-pilot-monitored-v1'
OUTPUT = P / 'outbound-five-aggregate-v1'
GIB = 1024**3
ONE = struct.pack('<f', 1.0)
ZERO = b'\0' * 4
FICLONE = 0x40049409


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


verify = load('outbound_five_verifier', HERE / 'verify.py')
mask = load('outbound_five_mask', ROOT / 'experiments/outbound-prefix-mask-v1/mask.py')
monitor = load('outbound_five_pilot_monitor', ROOT / 'experiments/outbound-diverse-prefix-pilot-v1/monitor.py')


def floor(path, amount):
    if shutil.disk_usage(path).free < amount:
        raise ValueError('insufficient free space; preserve incomplete output')


def local_source_chain():
    """Collect eager local Python modules, including spec-loaded helpers."""
    found = set(); seen = set(); todo = [monitor, mask, verify]
    while todo:
        module = todo.pop()
        if not isinstance(module, types.ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        name = getattr(module, '__file__', None)
        if not name:
            continue
        path = Path(name).absolute()
        if not path.resolve().is_relative_to(ROOT.resolve()):
            continue
        if path.is_symlink() or not path.is_file() or path.suffix != '.py':
            raise ValueError('invalid local Python source')
        found.add(path)
        todo.extend(value for value in vars(module).values() if isinstance(value, types.ModuleType))
    found.add(HERE / 'build.py'); found.add(HERE / 'verify.py')
    return sorted(found)


def source_pins(frozen):
    pins = {}
    for path in local_source_chain(): pins[str(path)] = verify.sha(path)
    # The completed pilot pinned its transitive runtime and helper sources;
    # include that exact set as well as the newly imported builder/mask code.
    for name, expected in frozen.get('sourceFiles', {}).items():
        path = Path(name)
        actual = verify.sha(path)
        if actual != expected: raise ValueError('pilot source chain differs: ' + name)
        pins[str(path)] = actual
    return pins


def check_completion():
    completion = json.loads((MONITOR / 'completion.json').read_text())
    if (completion.get('status') != 'diagnostic_only' or completion.get('screenStatus') != 'screen_passed' or
            completion.get('trainingAuthorized') is not False):
        raise ValueError('pilot monitor did not complete with a qualifying screen')
    links = {'launchSHA256': MONITOR / 'launch.json', 'outerStatusSHA256': MONITOR / 'outer-monitor/supervisor-result.json',
             'frozenInputsSHA256': MONITOR / 'frozen-inputs.json', 'reportSHA256': PILOT / 'report.json',
             'evidenceSHA256': MONITOR / 'evidence.json', 'telemetrySHA256': MONITOR / 'telemetry.jsonl',
             'diskSHA256': MONITOR / 'disk.jsonl', 'finalInventoryStatusSHA256': MONITOR / 'final-inventory-monitor/supervisor-result.json'}
    for key, path in links.items():
        if path.is_symlink() or not path.is_file() or completion.get(key) != verify.sha(path):
            raise ValueError('pilot completion evidence missing or changed: ' + key)
    frozen = json.loads((MONITOR / 'frozen-inputs.json').read_text())
    if monitor.pilot.pin_inputs() != frozen:
        raise ValueError('pilot registered inputs changed')
    monitor.old.verify_logs(MONITOR)
    if monitor.final_check(MONITOR, completion['evidenceSHA256']) != {'status': 'final_inventory_verified'}:
        raise ValueError('pilot final inventory did not verify')
    if json.loads((MONITOR / 'final-inventory-monitor/client.log').read_text()) != {'status': 'final_inventory_verified'}:
        raise ValueError('pilot final inventory process report differs')
    if json.loads((MONITOR / 'monitor-result.json').read_text()) != {'status': 'passed'}:
        raise ValueError('pilot resource monitor did not pass')
    for path in (MONITOR / 'outer-monitor/supervisor-result.json', MONITOR / 'final-inventory-monitor/supervisor-result.json'):
        if not monitor.pilot.clean(json.loads(path.read_text())):
            raise ValueError('pilot supervisor did not exit cleanly')
    saved = json.loads((PILOT / 'report.json').read_text())
    if monitor.verify_pilot(frozen) != saved:
        raise ValueError('pilot saved-game audit differs')
    return completion, saved, frozen


def source_checks():
    completion, report, frozen = check_completion()
    fit = [game for game in report['games'] if game['fitting'] and game['teacherHelpful']]
    if [x['index'] for x in fit] != [3, 4, 5, 6, 8] or any(x['teacherWorse'] for x in fit):
        raise ValueError('screened fitting identities differ')
    model = json.loads((PILOT / 'student/policy/receipt.json').read_text())
    base_data, base_map = BASE / 'data.bin', BASE / 'map.bin'
    teacher, teacher_map = PILOT / 'teacher/data.bin', PILOT / 'teacher/map.bin'
    paths = [base_data, base_map, teacher, teacher_map, PILOT / 'teacher/report.json',
             PILOT / 'student/policy/receipt.json', MONITOR / 'completion.json', PILOT / 'report.json',
             HERE / 'build.py', HERE / 'verify.py', HERE / 'supervise.py',
             ROOT / 'experiments/outbound-prefix-mask-v1/mask.py']
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError('invalid source file')
    hashes = {str(path): verify.sha(path) for path in paths}
    hashes.update(source_pins(frozen))
    if (hashes[str(base_data)] != model.get('dataSHA256') or
            hashes[str(base_map)] != model.get('memoryMapTargetsSHA256')):
        raise ValueError('baseline aggregate differs from selected student provenance')
    teacher_report = json.loads((PILOT / 'teacher/report.json').read_text())
    if (teacher_report.get('dataSHA256') != hashes[str(teacher)] or
            teacher_report.get('mapSHA256') != hashes[str(teacher_map)] or
            teacher_report.get('studentDriven') is not False or
            teacher_report.get('teacher') != 'exploring fetch teacher'):
        raise ValueError('teacher data differs from report')
    import mmap
    selected = []
    with teacher.open('rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as raw:
        mask.header(raw, b'PVDATA01', mask.IMAGE + mask.RAW_ROW)
        for game in fit:
            index = game['index']; run = PILOT / 'teacher' / f'expert-{index}'
            paths = [run / 'decisions.jsonl', run / 'result.json', run / 'initial.json', run / 'chase.jsonl']
            if any(path.is_symlink() or not path.is_file() for path in paths):
                raise ValueError('invalid selected episode evidence')
            for path in paths: hashes[str(path)] = verify.sha(path)
            cutoff = mask.decisions(*paths, raw, index, game['seed'])
            if cutoff is None or cutoff > 200:
                raise ValueError('selected episode lacks qualifying consumption')
            selected.append((index, cutoff))
    if selected != [(3, 162), (4, 107), (5, 171), (6, 43), (8, 38)]:
        raise ValueError('qualified consumption boundaries changed')
    return hashes, selected, completion, frozen


def clone(source, destination):
    # Exclusive creation and FICLONE only. No hard links and no implicit
    # fallback to a second copy; partial outputs are retained on failure.
    with Path(source).open('rb') as src, Path(destination).open('xb') as dst:
        if os.fstat(src.fileno()).st_dev != os.fstat(dst.fileno()).st_dev:
            raise ValueError('source and output differ in filesystem')
        fcntl.ioctl(dst.fileno(), FICLONE, src.fileno())
        if (os.fstat(src.fileno()).st_ino == os.fstat(dst.fileno()).st_ino or
                os.fstat(src.fileno()).st_nlink != 1 or os.fstat(dst.fileno()).st_nlink != 1):
            raise ValueError('clone alias or hard link detected')
        dst.flush(); os.fsync(dst.fileno())


def move_validation(file, old_count, old_fit, count, stride, min_free):
    new_size = 32 + (old_count + count) * stride
    file.truncate(new_size)
    for index in range(old_count - 1, old_fit - 1, -1):
        floor(Path(file.name).parent, min_free)
        file.seek(32 + index * stride); data = file.read(stride)
        if len(data) != stride: raise ValueError('short baseline validation episode')
        file.seek(32 + (index + count) * stride); file.write(data)
        floor(Path(file.name).parent, min_free)


def create_data(base, base_map, teacher, teacher_map, output, selected, *, old_count=1024, old_fit=928,
                teacher_count=12, teacher_fit=9, length=300, image=21168, raw_row=44, row=56, map_row=144,
                min_free=34 * GIB, reserve=36 * GIB):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink(): raise FileExistsError('output exists')
    sources = [Path(p).absolute() for p in (base, base_map, teacher, teacher_map)]
    if any(p.is_symlink() or not p.is_file() for p in sources): raise ValueError('invalid source')
    if any(output.resolve().is_relative_to(p.parent.resolve()) for p in sources):
        raise ValueError('output inside a source tree')
    if len({p.resolve() for p in sources}) != len(sources): raise ValueError('aliased sources')
    if (not selected or len({x[0] for x in selected}) != len(selected) or
            any(type(i) is not int or type(c) is not int or not 0 <= i < teacher_fit or not 1 <= c <= length for i,c in selected)):
        raise ValueError('invalid selected episodes')
    n = old_count + len(selected); fit = old_fit + len(selected)
    ostride = length * (image + row); rstride = length * (image + raw_row); mstride = length * map_row
    full_reservation = 64 + n * (ostride + mstride)
    floor(output.parent, reserve + full_reservation)
    import mmap
    with sources[0].open('rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        verify.dims(data,b'PVDATA04',old_count,old_fit,length,image+row)
    with sources[1].open('rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        verify.dims(data,b'PVMAP001',old_count,old_fit,length,map_row)
    with sources[2].open('rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        verify.dims(data,b'PVDATA01',teacher_count,teacher_fit,length,image+raw_row)
    with sources[3].open('rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        verify.dims(data,b'PVMAP001',teacher_count,teacher_fit,length,map_row)
    output.mkdir(); clone(sources[0],output/'data.bin'); clone(sources[1],output/'map.bin')
    with (output/'data.bin').open('r+b') as dst, (output/'map.bin').open('r+b') as maps, sources[2].open('rb') as src, sources[3].open('rb') as srcmap:
        move_validation(dst,old_count,old_fit,len(selected),ostride,min_free)
        move_validation(maps,old_count,old_fit,len(selected),mstride,min_free)
        for dest, (index, cutoff) in enumerate(selected,old_fit):
            floor(output,min_free)
            src.seek(32+index*rstride); images=src.read(length*image); raw=src.read(length*raw_row)
            srcmap.seek(32+index*mstride); mapbytes=srcmap.read(mstride)
            if len(images)!=length*image or len(raw)!=length*raw_row or len(mapbytes)!=mstride: raise ValueError('short teacher record')
            rows=bytearray()
            for t in range(length):
                x=raw[t*raw_row:(t+1)*raw_row]
                if x[40:44] not in (ZERO,ONE): raise ValueError('invalid teacher weight')
                rows.extend(x[:40] + (ZERO if t>=cutoff else x[40:44]) + ONE + x[28:36])
            dst.seek(32+dest*ostride); dst.write(images); dst.write(rows)
            maps.seek(32+dest*mstride); maps.write(mapbytes)
            floor(output,min_free)
        for stream in (dst,maps):
            stream.seek(8); stream.write(struct.pack('<3q',n,fit,length)); stream.flush(); os.fsync(stream.fileno())
    return verify.verify(*sources,output/'data.bin',output/'map.bin',selected,old_count=old_count,old_fit=old_fit,
                         teacher_count=teacher_count,teacher_fit=teacher_fit,length=length,image=image,
                         raw_row=raw_row,row=row,map_row=map_row)


def run():
    if OUTPUT.exists() or OUTPUT.is_symlink(): raise FileExistsError('output exists; preserve it')
    sources, selected, completion, frozen = source_checks()
    outcome = create_data(BASE/'data.bin',BASE/'map.bin',PILOT/'teacher/data.bin',PILOT/'teacher/map.bin',OUTPUT,selected)
    if any(verify.sha(path) != digest for path,digest in sources.items()):
        raise ValueError('source changed during creation; candidate is incomplete')
    completed_after, report_after, frozen_after = check_completion()
    if (completed_after != completion or report_after.get('status') != 'screen_passed' or
            frozen_after != frozen or source_pins(frozen_after) != source_pins(frozen)):
        raise ValueError('pilot changed or failed re-audit during creation')
    floor(OUTPUT,36*GIB)
    report = {'schema':'puppybot.outbound-five-aggregate.v1','status':'candidate_data_only',
              'trainingAuthorized':False,'sourceFiles':sources,'pilotCompletionSHA256':verify.sha(MONITOR/'completion.json'),
              'selectedTeacherEpisodes':[{'episode':i,'seed':6910000+i,'firstConsumptionAction':c,'destinationEpisode':928+j}
                                         for j,(i,c) in enumerate(selected)],
              'verification':outcome,'dataSHA256':verify.sha(OUTPUT/'data.bin'),'mapSHA256':verify.sha(OUTPUT/'map.bin'),
              'scope':'screened local simulated teacher prefixes; no model, held-out or physical performance claim'}
    target=OUTPUT/'report.json'
    with target.open('x') as f: json.dump(report,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
    return report


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and bounded scheduling.')
