#!/usr/bin/env python3
"""Build copied simulator and failure-stop probe; does not launch either."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
CONTACT = P / 'contact-stop-build-v1'
SIM = P / 'physical-dock-confirm-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


contact = load('fault_contact_build', ROOT / 'experiments/contact-stop-trial-v1/build.py')
dock = load('fault_dock_runner', ROOT / 'experiments/physical-dock-confirm-trial-v1/run.py')
transform = load('fault_transform', ROOT / 'experiments/contact-stop-io-failsafe-v1/transform.py')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''): digest.update(part)
    return digest.hexdigest()


def once(source, old, new):
    if source.count(old) != 1: raise ValueError('unexpected simulator source')
    return source.replace(old, new, 1)


def mark_simulator(source):
    """Report only after command 3 was read and drive state was zeroed."""
    source = once(source, '    let request = alloc(64); let running = 1;\n',
                  '    let request = alloc(64); let running = 1; let test_stop = 0;\n')
    source = once(source, '        if command == 3 { running = 0; }\n',
                  '        if command == 3 { running = 0; test_stop = 1; }\n')
    return once(source,
        '    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_discovery_phase = 6;\n',
        '    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_discovery_phase = 6;\n'
        '    if test_stop { let drive = pb_robot_drive(ps_robot); '
        'if !load64(drive + 48) && !load64(drive + 56) && !load64(drive + 72) '
        '{ pl_print(2, "FAULT_TEST_SIM_STOP_ZERO\\n"); } '
        'else { pl_print(2, "FAULT_TEST_SIM_STOP_NONZERO\\n"); } }\n')


def inputs():
    a = contact.verify(); b = dock.check_build(SIM)
    return {'contactReceipt': sha(CONTACT / 'build.json'), 'contactControl': a['controlSHA256'],
            'simReceipt': sha(SIM / 'build.json'), 'simulator': b['simulatorSHA256'],
            'compiler': sha(COMPILER), 'transform': sha(Path(transform.__file__)),
            'probe': sha(HERE / 'probe.flex'), 'builder': sha(Path(__file__))}


def build(output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink(): raise FileExistsError('preserve existing output')
    pinned = inputs(); output.mkdir()
    # Import paths in this archived build are relative to source/ and build/.
    source = output / 'source'; library_root = output / 'build'
    shutil.copytree(SIM / 'source', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(SIM / 'build', library_root, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    library = library_root / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
    old = f'import "{SIM / "source/core/words.flex"}";'
    new = f'import "{source / "core/words.flex"}";'
    adapter.write_text(once(adapter.read_text(), old, new))
    (library.parent / 'dependencies.flex').write_text(
        f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
    agent = source / 'sim/agent.flex'; agent.write_text(mark_simulator(agent.read_text()))
    controls = output / 'control-source'; shutil.copytree(CONTACT / 'flex-source', controls,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    control = controls / 'control'
    host, environment, main = transform.transform(*(control.joinpath(name).read_text()
                                                   for name in ('host.flex', 'environment.flex', 'main.flex')))
    for name, value in (('host.flex', host), ('environment.flex', environment), ('main.flex', main)):
        (control / name).write_text(value)
    shutil.copyfile(HERE / 'probe.flex', control / 'fault-probe.flex')
    for src, binary in ((source / 'sim/main.flex', output / 'simulator'),
                        (control / 'fault-probe.flex', output / 'probe')):
        subprocess.run([str(COMPILER), str(src), '-o', str(binary)], cwd=ROOT,
                       capture_output=True, check=True, timeout=120)
    if inputs() != pinned: raise ValueError('inputs changed during build')
    result = {'schema': 'puppybot.sim-fault-real-peer-build.v1', 'inputs': pinned,
              'simulatorSHA256': sha(output / 'simulator'), 'probeSHA256': sha(output / 'probe'),
              'simSource': contact.base.hidden.supervisor.source_hashes(source),
              'controlSource': contact.base.hidden.supervisor.source_hashes(controls),
              'library': dock.base.prepare.hashes(library),
              'dependenciesSHA256': sha(library.parent / 'dependencies.flex'),
              'scope': 'instrumented simulator and probe; no execution attestation or physical claim'}
    (output / 'build.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    if verify(output) != result: raise ValueError('built files changed')
    return result


def verify(output):
    output = Path(output).absolute(); result = json.loads((output / 'build.json').read_text())
    if result.get('schema') != 'puppybot.sim-fault-real-peer-build.v1' or result.get('inputs') != inputs():
        raise ValueError('build provenance changed')
    source = output / 'source'; controls = output / 'control-source'; library = output / 'build/flex/sim/library'
    if (contact.base.hidden.supervisor.source_hashes(source) != result['simSource'] or
            contact.base.hidden.supervisor.source_hashes(controls) != result['controlSource'] or
            dock.base.prepare.hashes(library) != result['library'] or
            sha(library.parent / 'dependencies.flex') != result['dependenciesSHA256'] or
            sha(output / 'simulator') != result['simulatorSHA256'] or sha(output / 'probe') != result['probeSHA256']):
        raise ValueError('built input or executable changed')
    dependency = f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n'
    if (library.parent / 'dependencies.flex').read_text() != dependency: raise ValueError('dependency adapter differs')
    old_library = SIM / 'build/flex/sim/library'; old_hashes = dock.base.prepare.hashes(old_library)
    if set(old_hashes) != set(result['library']): raise ValueError('library inventory differs')
    for name, digest in old_hashes.items():
        if name == 'lib/f64.flex':
            old = f'import "{SIM / "source/core/words.flex"}";'
            new = f'import "{source / "core/words.flex"}";'
            if (library / name).read_text() != once((old_library / name).read_text(), old, new):
                raise ValueError('library adapter differs')
        elif result['library'][name] != digest: raise ValueError('unrelated library source differs')
    original_source = SIM / 'source'; original_control = CONTACT / 'flex-source'
    old = contact.base.hidden.supervisor.source_hashes(original_source)
    if set(result['simSource']) != set(old): raise ValueError('simulator source inventory differs')
    for name, digest in old.items():
        if name == 'sim/agent.flex':
            if (source / name).read_text() != mark_simulator((original_source / name).read_text()):
                raise ValueError('simulator instrumentation differs')
        elif result['simSource'][name] != digest: raise ValueError('unrelated simulator source differs')
    old = contact.base.hidden.supervisor.source_hashes(original_control)
    if set(result['controlSource']) != set(old) | {'control/fault-probe.flex'}:
        raise ValueError('control source inventory differs')
    for name, digest in old.items():
        if name not in ('control/host.flex', 'control/environment.flex', 'control/main.flex') and result['controlSource'][name] != digest:
            raise ValueError('unrelated control source differs')
    generated = transform.transform(*((original_control / 'control' / name).read_text()
                                      for name in ('host.flex', 'environment.flex', 'main.flex')))
    for name, value in zip(('host.flex', 'environment.flex', 'main.flex'), generated):
        if (controls / 'control' / name).read_text() != value: raise ValueError('control transform differs')
    if (controls / 'control/fault-probe.flex').read_bytes() != (HERE / 'probe.flex').read_bytes():
        raise ValueError('probe source differs')
    return result


if __name__ == '__main__':
    raise SystemExit('Disabled: build requires reviewed low-priority, locked supervision.')
