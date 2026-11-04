#!/usr/bin/env python3
"""Read-only design and preflight for a fresh-seed teacher/student pilot.

Importing or calling preflight does not create output. Explicit staging and
freeze functions exist, but no collection or training launcher is provided.
The scenes are previously used training-family layouts, not held-out scenes.
"""
import importlib.util
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
SCENES = ROOT / 'build/flex/sim/expanded-rooms-v1/scenes'
MODEL = P / 'search-dagger-l35-4workers/student-s1'
OUTPUT = P / 'outbound-teacher-prefix-pilot-v1'
CATALOG = OUTPUT / 'catalog'
BASE_SEED = 6910000
GAMES = 12
FITTING = 9
HORIZON = 300


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


register = load('outbound_seed_inventory', ROOT / 'experiments/l5-steering-kick-v1/register.py')
selection = load('outbound_fresh_selection', ROOT / 'experiments/fresh-policy-comparison-v1/selection.py')
heldout = load('outbound_heldout_seed_spec', ROOT / 'datasets/visual-control/chase-v1/levels/prepare-heldout.py')
validation = load('outbound_validation_seed_spec', ROOT / 'datasets/visual-control/chase-v1/levels/prepare-bias-validation.py')


def design():
    # Fitting and validation cases span the same three fitting-layout families.
    # These layouts and variants have appeared before; seed separation is not
    # evidence of independent geometry or unknown model ancestry.
    specs = [(layout, variant, True) for layout in (13, 15, 17) for variant in (8, 9, 10)]
    specs += [(layout, 11, False) for layout in (13, 15, 17)]
    rows = []
    for index, (layout, variant, fitting) in enumerate(specs):
        rows.append({'index': index, 'seed': BASE_SEED + index, 'layout': layout,
                     'variant': variant, 'fitting': fitting,
                     'scene': str(SCENES / str(layout) / str(variant))})
    return {'schema': 'puppybot.outbound-teacher-prefix-pilot-design.v1',
            'status': 'draft_not_registered', 'rows': rows, 'horizon': HORIZON,
            'fittingGames': FITTING, 'validationGames': GAMES - FITTING,
            'level': 5, 'cameraPitch': 82, 'model': str(MODEL),
            'arms': ['student', 'teacher'],
            'gate': {'teacherPickupNoLaterThan': 200, 'minimumEarlierActions': 30,
                     'maximumTeacherOutboundBackForthActions': 0,
                     'minimumHelpfulFittingGames': 3, 'minimumHelpfulFittingLayouts': 2,
                     'minimumHelpfulValidationGames': 1, 'maximumTeacherWorseGames': 3},
            'scope': '12 matched reused training-family scenes and new seeds; no held-out, physical or promotion claim'}


def check_seed_boundaries(rows, reserved, selection_seeds, validation_seeds):
    seeds = [row['seed'] for row in rows]
    if len(seeds) != GAMES or len(set(seeds)) != GAMES:
        raise ValueError('incorrect or duplicate pilot seeds')
    if set(seeds) & (set(reserved) | set(selection_seeds) | set(validation_seeds)):
        raise ValueError('pilot seed overlaps reserved selection, validation or held-out seeds')


def command(arm, output):
    if arm not in ('student', 'teacher'):
        raise ValueError('unknown arm')
    argv = [str(ROOT / 'build/flex/control/control'), 'collect', '--chase',
            '--scene-catalog', str(CATALOG), '--output', str(output), '--episodes', str(GAMES),
            '--validation', str(GAMES - FITTING), '--horizon', str(HORIZON), '--seed', str(BASE_SEED),
            '--lean', '--wheel-odometry', '--fetch', '--explore-teacher', '--level', '5',
            '--camera-pitch', '82', '--record-map']
    if arm == 'student':
        argv += ['--policy', str(MODEL)]
    return argv


def environment():
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
            'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}


def preflight():
    rows = design()['rows']
    reserved = {heldout.BASE_SEED + level * 100 + i for level in range(1, 6) for i in range(32)}
    selection_seeds = (set(range(7800000, 7800032)) |
                       set(range(selection.SEED, selection.SEED + selection.GAMES)) |
                       set(range(990000, 990032)))
    check_seed_boundaries(rows, reserved, selection_seeds, validation.SEEDS)
    # historical_inventory reads only named, non-held-out report/result roots;
    # skipped symlinks and unrecorded history remain an explicit limitation.
    register.plan.design = lambda: {'conditions': [{'seed': row['seed']} for row in rows]}
    extra = ('search-mix-selection', 'l5-teacher-rollin-pilot-v1',
             'l5-steering-kick-diagnostic-v1', 'l5-steering-hysteresis-diagnostic-v1',
             'l5-steering-hysteresis-debug-v1', 'contact-stop-trial-v2')
    roots = register.HISTORY + tuple(P / name for name in extra if (P / name).is_dir())
    history = register.historical_inventory(roots=roots, require_known=True)
    scenes = []
    for row in rows:
        links = selection.scene_links(row)
        scene = Path(row['scene'])
        metadata = json.loads((scene / 'layout.json').read_text())
        if (metadata.get('layoutId') != row['layout'] or metadata.get('fit') is not True or
                metadata.get('reservedHeldOut') is True or metadata.get('startRoom') != 0):
            raise ValueError('source scene is not declared fitting')
        scenes.append({**row, 'links': links,
                       'files': {name: register.base.sha(scene / name)
                                 for name in ('case.json', 'environment.bin', 'layout.json')}})
    _, files = selection.auditor.qualification.model_files(MODEL)
    levels = ROOT / 'datasets/visual-control/chase-v1/levels'
    inputs = [Path(__file__), ROOT / 'experiments/outbound-teacher-prefix-pilot-v1/screen.py',
              ROOT / 'experiments/outbound-teacher-prefix-pilot-v1/audit.py',
              ROOT / 'experiments/l5-teacher-rollin-pilot-v1/pilot.py',
              ROOT / 'experiments/outbound-teacher-audit-v1/audit.py',
              ROOT / 'experiments/heading-teacher-audit/audit.py',
              ROOT / 'experiments/fresh-policy-comparison-v1/selection.py',
              ROOT / 'experiments/l5-steering-hysteresis-v1/monitor.py',
              ROOT / 'experiments/l5-steering-kick-v1/register.py',
              ROOT / 'experiments/l5-steering-kick-v1/plan.py',
              ROOT / 'experiments/l5-steering-kick-v1/prepare.py',
              ROOT / 'experiments/l5-steering-kick-v1/transform.py',
              ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
              ROOT / 'experiments/sim-stop-supervisor/proxy.py',
              ROOT / 'flex/tests/run-physical-hidden-trial.py',
              ROOT / 'flex/tests/run-physical-rescan-trial.py',
              ROOT / 'flex/tests/run-physical-hybrid-trial.py', Path(sys.executable).resolve(),
              ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
              ROOT / 'flex/tests/sim-cases.py', ROOT / 'flex/tests/sim.py',
              ROOT / 'build/flex/control/control', ROOT / 'build/flex/control/simulator',
              ROOT / 'build/flex/sim/puppybot.bin', ROOT / 'puppybot.json']
    inputs += [levels / name for name in ('audit-shards.py', 'audit-selection.py', 'audit-heldout.py',
              'qualify-selection.py', 'heading-selection-metrics.py', 'search-loops-odometry.py',
              'prepare-heldout.py', 'prepare-bias-validation.py', 'prepare-route-factorial.py',
              'run-route-factorial.py', 'route-coverage.py', 'package-matched-epoch8.py',
              'audit-matched-training.py')]
    return {'status': 'preflight_only', 'design': design(), 'scenes': scenes,
            'modelFiles': {str(path): register.base.sha(path) for path in files},
            'sourceFiles': {str(path): register.base.sha(path) for path in inputs},
            'runtime': register.runtime_chain(),
            'history': history,
            'scope': 'read-only local inputs; named-root seed inventory skips symlinks and cannot establish unrecorded history or ancestry'}


def prepare_catalog():
    """Copy one shared student/teacher catalog under the existing advisory lock.

    This is an input staging step, not a GPU run, frozen launch registration,
    or evidence that the teacher is useful. Partial output is never removed.
    """
    with register.base.acquire_lock(P / '.l4-matched.lock'):
        if OUTPUT.exists() or OUTPUT.is_symlink():
            raise FileExistsError('output exists; preserve it')
        if shutil.disk_usage(P).free < 36 * 1024**3:
            raise ValueError('less than 36 GiB available')
        inputs = preflight()
        OUTPUT.mkdir(); CATALOG.mkdir()
        for row in inputs['scenes']:
            target = CATALOG / str(row['index']); target.mkdir()
            source = Path(row['scene'])
            for name in ('case.json', 'environment.bin', 'layout.json'):
                shutil.copyfile(source / name, target / name)
                if register.base.sha(target / name) != row['files'][name]:
                    raise ValueError('copied catalog differs')
        if preflight() != inputs:
            raise ValueError('source inputs changed during catalog preparation')
        manifest = {'status': 'catalog_inputs_only', 'inputs': inputs,
                    'scope': 'same local catalog for both arms; no collection or training'}
        with (OUTPUT / 'catalog.json').open('x') as stream:
            json.dump(manifest, stream, sort_keys=True, indent=2); stream.write('\n')
        return manifest


def verify_catalog(inputs):
    if (CATALOG.is_symlink() or not CATALOG.is_dir() or
            {path.name for path in CATALOG.iterdir()} != {str(i) for i in range(GAMES)}):
        raise ValueError('catalog inventory differs')
    for row in inputs['scenes']:
        target = CATALOG / str(row['index'])
        if target.is_symlink() or not target.is_dir() or {p.name for p in target.iterdir()} != {'case.json', 'environment.bin', 'layout.json'}:
            raise ValueError('catalog scene inventory differs')
        for name in ('case.json', 'environment.bin', 'layout.json'):
            path = target / name
            if path.is_symlink() or not path.is_file() or register.base.sha(path) != row['files'][name]:
                raise ValueError('catalog file differs')


def freeze():
    """Freeze commands after catalog staging and before either arm plays.

    A separately reviewed bounded GPU/disk supervisor is still required; this
    function neither launches collection nor proves operating-system identity.
    """
    with register.base.acquire_lock(P / '.l4-matched.lock'):
        if shutil.disk_usage(P).free < 36 * 1024**3:
            raise ValueError('less than 36 GiB available')
        receipt = OUTPUT / 'catalog.json'; destination = OUTPUT / 'launch-plan.json'
        if destination.exists() or destination.is_symlink():
            raise FileExistsError('launch plan exists; preserve it')
        for name in ('student', 'teacher', 'monitor-student', 'monitor-teacher'):
            if (OUTPUT / name).exists() or (OUTPUT / name).is_symlink():
                raise ValueError('pilot arm output already exists')
        if not receipt.is_file() or receipt.is_symlink():
            raise ValueError('catalog receipt missing')
        catalog = json.loads(receipt.read_text()); inputs = preflight()
        if catalog.get('status') != 'catalog_inputs_only' or catalog.get('inputs') != inputs:
            raise ValueError('catalog input receipt differs')
        verify_catalog(inputs)
        result = {'schema': 'puppybot.outbound-teacher-prefix-pilot-launch.v1',
                  'status': 'frozen_before_play', 'catalogSHA256': register.base.sha(receipt),
                  'inputs': inputs, 'commands': {arm: command(arm, OUTPUT / arm) for arm in design()['arms']},
                  'environment': environment(), 'wallSecondsPerArm': 3600,
                  'scope': 'recorded local input and launch intent only; external GPU/disk supervisor required'}
        with destination.open('x') as stream:
            json.dump(result, stream, sort_keys=True, indent=2); stream.write('\n')
        return result


if __name__ == '__main__':
    raise SystemExit('Disabled: this is a read-only preflight, not a frozen plan or GPU launcher.')
