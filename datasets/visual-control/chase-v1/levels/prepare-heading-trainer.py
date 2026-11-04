#!/usr/bin/env python3
"""Build an isolated training control with verified FICLONE dataset copies.

Staged prototype only. Requires the small roll-in pilot, not full collection.
Compiles a private source snapshot, runs CPU-only probe against new scratch
files, and never rewrites an existing data/model artifact.
A successful build is not a trained policy or physical-robot evidence.
"""
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'search-dagger-heading'
BUILD = P / 'search-dagger-heading-trainer-build'
COMPILER = PROJECT / 'build/flex/control/compiler'


def load(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


transform = load('reflink_source', S / 'heading-reflink-source.py')
pair = load('heading_pair', S / 'verify-heading-overlay-pair.py')
hybrid = load('hybrid', PROJECT / 'flex/tests/run-physical-hybrid-trial.py')


def verify(build, manifest):
    if hybrid.source_hashes(build / 'flex-source') != manifest['patchedSourceFiles']:
        raise ValueError('private trainer source changed')
    source = build / 'dataset.original.flex'; original = source.read_text()
    if hybrid.sha(source) != manifest['originalDatasetSHA256']:
        raise ValueError('archived dataset source changed')
    if (build / 'flex-source/control/dataset.flex').read_text() != transform.transform(original):
        raise ValueError('reflink transform differs')
    restored = dict(manifest['patchedSourceFiles'])
    restored.pop('control/reflink-probe.flex', None)
    restored['control/dataset.flex'] = manifest['originalDatasetSHA256']
    if restored != manifest['originalSourceFiles']:
        raise ValueError('stock and reflink controls differ in other source files')
    if hybrid.sha(build / 'flex-source/control/reflink-probe.flex') != hybrid.sha(build / 'flex-source/tests/heading-reflink-native.flex'):
        raise ValueError('compiled reflink probe differs from archived test source')
    if kernel_pins() != manifest['trainingKernelsSHA256']:
        raise ValueError('trainer kernel inventory changed')
    for key, path in [('compilerSHA256', COMPILER), ('controlSHA256', build / 'control'),
                      ('stockControlSHA256', build / 'control-stock'),
                      ('probeSHA256', build / 'reflink-probe'), ('transformSHA256', S / 'heading-reflink-source.py'),
                      ('builderSHA256', Path(__file__)),
                      ('trainerSHA256', PROJECT / 'build/flex/control/trainer'),
                      ('policyBinarySHA256', PROJECT / 'build/flex/control/policy-categorical'),
                      ('policyGraphSHA256', PROJECT / 'flex/control/model-categorical.pup'),
                      ('policyFactorySHA256', PROJECT / 'build/flex/pixel-control-categorical-model.flex'),
                      ('hipRuntimeSHA256', PROJECT / 'build/flex/rocm-runtime/libamdhip64.so'),
                      ('pilotReportSHA256', pair.rollin.PILOT / 'pilot-report.json'),
                      ('probeSourceSHA256', build / 'probe-fixture/source'), ('probeTargetSHA256', build / 'probe-fixture/target')]:
        if hybrid.sha(path) != manifest[key]: raise ValueError(f'trainer input changed: {path}')
    if manifest['probeSourceSHA256'] != manifest['probeTargetSHA256']:
        raise ValueError('trainer probe source and target differ')
    current = subprocess.run(['btrfs', 'filesystem', 'du', '--raw', '-s', str(build / 'probe-fixture/source'), str(build / 'probe-fixture/target')],
                             cwd=PROJECT, check=True, text=True, capture_output=True).stdout
    if current != manifest['probeExtents']:
        raise ValueError('trainer probe extent sharing changed')


def kernel_pins():
    root = PROJECT / 'build/flex/control/kernels'
    files = sorted(path for path in root.rglob('*') if path.is_file())
    if not files: raise ValueError('trainer kernels are missing')
    return {str(path.relative_to(root)): hybrid.sha(path) for path in files}


def verify_pilot_data():
    rollin = pair.rollin; root = rollin.PILOT; catalogs = rollin.PILOT_CATALOGS
    manifest = json.loads((catalogs / 'catalogs.json').read_text()); rollin.catalogs.verify(catalogs, manifest)
    if rollin.critical(catalogs, manifest) != json.loads((root / 'inputs.json').read_text()):
        raise ValueError('roll-in pilot inputs changed')
    report = json.loads((root / 'pilot-report.json').read_text())
    if (report.get('status') != 'passed' or report.get('parentWeightsSHA256') != hybrid.sha(rollin.PARENT / 'weights.bin') or
            report.get('reports') != rollin.validate_matched(root, 'pilot', manifest)):
        raise ValueError('roll-in pilot source audit differs')
    aggregate = report['pilotAggregate']
    actual = {arm: {name: hybrid.sha(root / f'aggregate-{arm}' / name) for name in ('data.bin', 'map.bin')}
              for arm in ('control', 'treatment')}
    if actual != aggregate['aggregateHashes'] or pair.pairs.compare_validation(root / 'aggregate-control', root / 'aggregate-treatment', 34, 31) != aggregate['validation']:
        raise ValueError('roll-in pilot aggregates changed')
    teacher = P / 'kturn-L4/shard-4'
    for arm in ('control', 'treatment'):
        student = root / f'{arm}-L5/shard-0'; out = root / f'aggregate-{arm}'
        subprocess.run([sys.executable, '-I', str(S / 'audit-mixed-students.py'), str(out), '2', str(teacher), str(student)],
                       cwd=PROJECT, check=True, stdout=subprocess.DEVNULL, timeout=300)
    args = [sys.executable, '-I', str(S / 'audit-matched-l4.py'), str(root / 'aggregate-control'), str(root / 'aggregate-treatment'),
            str(teacher), str(teacher), str(root / 'control-L5/shard-0'), str(root / 'treatment-L5/shard-0')]
    checked = subprocess.run(args, cwd=PROJECT, check=True, capture_output=True, text=True, timeout=300)
    if json.loads(checked.stdout) != aggregate['unchanged']:
        raise ValueError('roll-in pilot unchanged games differ')
    proof = aggregate['overlayProof']; source = root / 'aggregate-control'; candidate = root / 'overlay-treatment'
    for name, key in (('manifest.json', 'manifestSHA256'), ('data.bin', 'dataSHA256'), ('map.bin', 'mapSHA256')):
        if hybrid.sha(candidate / name) != proof[key]: raise ValueError('pilot overlay changed')
    if proof.get('validation') != 'byte_equal_at_check': raise ValueError('pilot overlay lacks paired validation')
    for name in ('data.bin', 'map.bin'):
        if [list(span) for span in rollin.overlay.physical_map(source / name)] != proof['sourcePhysicalMap'][name]:
            raise ValueError('pilot aggregate physical mapping changed')
        subprocess.run(['/usr/bin/cmp', '-s', str(candidate / name), str(root / 'aggregate-treatment' / name)], check=True, timeout=300)
    pair.pairs.compare_validation(source, candidate, 34, 31)
    mapping = {30: (root / 'treatment-L5/shard-0', 0), 33: (root / 'treatment-L5/shard-0', 1)}
    rollin.overlay.audit(source, candidate, mapping, 34)
    return report


def verify_ready():
    receipt = json.loads((OUTPUT / 'pair-ready.json').read_text()); pair.verify_tool_pins(receipt)
    if receipt.get('status') != 'paired_inputs_only' or receipt['aggregateValidation']['validationGames'] != 96:
        raise ValueError('paired input receipt missing or invalid')
    catalog_manifest = json.loads((pair.CATALOGS / 'catalogs.json').read_text())
    pair.rollin.catalogs.verify(pair.CATALOGS, catalog_manifest)
    if receipt.get('catalogsSHA256') != hybrid.sha(pair.CATALOGS / 'catalogs.json') or receipt.get('collectionReportSHA256') != hybrid.sha(OUTPUT / 'collection-report.json'):
        raise ValueError('paired source metadata changed')
    if pair.rollin.critical(pair.CATALOGS, catalog_manifest) != json.loads((OUTPUT / 'inputs.json').read_text()):
        raise ValueError('roll-in inputs changed')
    collection = json.loads((OUTPUT / 'collection-report.json').read_text())
    if collection.get('status') != 'passed' or collection.get('reports') != pair.rollin.validate_matched(OUTPUT, 'full', catalog_manifest):
        raise ValueError('collection audit differs')
    subprocess.run(['/usr/bin/sha256sum', '-c', str(pair.PREVIOUS / 'training-inputs.sha256')], cwd=PROJECT, check=True, stdout=subprocess.DEVNULL)
    plan = pair.slots.fixed_plan()
    left = [OUTPUT / f'control-L5/shard-{i}' for i in range(4)]
    right = [OUTPUT / f'treatment-L5/shard-{i}' for i in range(4)]
    actual = pair.check_pair(pair.PREVIOUS / 'data', OUTPUT / 'aggregate-control', OUTPUT / 'aggregate-treatment', left, right, plan)
    for key in ('status', 'plan', 'control', 'treatment', 'aggregateValidation', 'sharedHeadingShardBytes'):
        if actual[key] != receipt.get(key): raise ValueError(f'paired input receipt differs: {key}')
    return receipt


def main():
    if len(sys.argv) != 1: raise SystemExit(__doc__)
    os.chdir(PROJECT)
    with pair.rollin.base.acquire_lock(P / '.l4-matched.lock'):
        pair.rollin.base.require_capacity(P, 34 * 1024**3)
        pair.rollin.base.require_new_output(BUILD)
        verify_pilot_data()
        worktree = hybrid.source_hashes(PROJECT / 'flex'); compiler = hybrid.sha(COMPILER)
        trainer = hybrid.sha(PROJECT / 'build/flex/control/trainer'); source_sha = hybrid.sha(S / 'heading-reflink-source.py')
        kernels = kernel_pins()
        policy_binary = hybrid.sha(PROJECT / 'build/flex/control/policy-categorical')
        policy_graph = hybrid.sha(PROJECT / 'flex/control/model-categorical.pup')
        policy_factory = hybrid.sha(PROJECT / 'build/flex/pixel-control-categorical-model.flex')
        hip = hybrid.sha(PROJECT / 'build/flex/rocm-runtime/libamdhip64.so')
        BUILD.mkdir()
        shutil.copytree(PROJECT / 'flex', BUILD / 'flex-source', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        if hybrid.source_hashes(BUILD / 'flex-source') != worktree or hybrid.source_hashes(PROJECT / 'flex') != worktree:
            raise ValueError('source changed while snapshotting')
        source = BUILD / 'flex-source/control/dataset.flex'; original = source.read_text()
        (BUILD / 'dataset.original.flex').write_text(original)
        subprocess.run([str(COMPILER), str(BUILD / 'flex-source/control/main.flex'), '-o', str(BUILD / 'control-stock')],
                       cwd=PROJECT, check=True, timeout=120)
        if hybrid.source_hashes(BUILD / 'flex-source') != worktree:
            raise ValueError('stock source changed during build')
        source.write_text(transform.transform(original))
        shutil.copyfile(BUILD / 'flex-source/tests/heading-reflink-native.flex', BUILD / 'flex-source/control/reflink-probe.flex')
        patched = hybrid.source_hashes(BUILD / 'flex-source')
        for input_name, output_name in (('main.flex', 'control'), ('reflink-probe.flex', 'reflink-probe')):
            subprocess.run([str(COMPILER), str(BUILD / 'flex-source/control' / input_name), '-o', str(BUILD / output_name)],
                           cwd=PROJECT, check=True, timeout=120)
        fixture = BUILD / 'probe-fixture'; fixture.mkdir()
        payload = b'PVDATA01' + struct.pack('<qqq', 2, 1, 1) + os.urandom(2 * 21212)
        with (fixture / 'source').open('xb') as f: f.write(payload); f.flush(); os.fsync(f.fileno())
        subprocess.run([str(BUILD / 'reflink-probe'), str(fixture / 'source'), str(fixture / 'target')], cwd=PROJECT, check=True, timeout=20)
        if (fixture / 'source').read_bytes() != payload or (fixture / 'target').read_bytes() != payload:
            raise ValueError('private trainer probe bytes differ')
        extents = subprocess.run(['btrfs', 'filesystem', 'du', '--raw', '-s', str(fixture / 'source'), str(fixture / 'target')],
                                 cwd=PROJECT, check=True, text=True, capture_output=True).stdout
        rows = extents.strip().splitlines()
        if len(rows) != 3: raise ValueError('unexpected trainer probe extent output')
        for row in rows[1:]:
            fields = row.split(maxsplit=3)
            if len(fields) != 4 or not all(x.isdigit() for x in fields[:3]): raise ValueError('invalid probe extent numbers')
            total, exclusive, shared = map(int, fields[:3])
            if total <= 0 or exclusive != 0 or shared != total: raise ValueError('trainer probe did not share its data extents')
        manifest = {'originalDatasetSHA256': hybrid.sha(BUILD / 'dataset.original.flex'), 'compilerSHA256': compiler,
                    'trainerSHA256': trainer, 'transformSHA256': source_sha, 'builderSHA256': hybrid.sha(Path(__file__)),
                    'policyBinarySHA256': policy_binary, 'policyGraphSHA256': policy_graph,
                    'policyFactorySHA256': policy_factory, 'hipRuntimeSHA256': hip,
                    'pilotReportSHA256': hybrid.sha(pair.rollin.PILOT / 'pilot-report.json'),
                    'controlSHA256': hybrid.sha(BUILD / 'control'), 'stockControlSHA256': hybrid.sha(BUILD / 'control-stock'),
                    'probeSHA256': hybrid.sha(BUILD / 'reflink-probe'), 'trainingKernelsSHA256': kernels,
                    'probeSourceSHA256': hybrid.sha(fixture / 'source'), 'probeTargetSHA256': hybrid.sha(fixture / 'target'),
                    'originalSourceFiles': worktree, 'patchedSourceFiles': patched, 'probeExtents': extents,
                    'scope': 'isolated training control; FICLONE only, source and target hashes checked; no full-copy fallback'}
        verify(BUILD, manifest)
        with (BUILD / 'inputs.json').open('x') as f:
            json.dump(manifest, f, sort_keys=True, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
        print(json.dumps({'status': 'built_cpu_only', 'controlSHA256': manifest['controlSHA256']}))


if __name__ == '__main__': main()
