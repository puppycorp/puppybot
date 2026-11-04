#!/usr/bin/env python3
"""Fixed exploratory training/evaluation design; no training or outputs."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
PARENT = P / 'search-dagger-l35-4workers/student-s1'
AGGREGATE = P / 'outbound-five-aggregate-v1'
TRAINER = P / 'outbound-five-trainer-build-v1'
MODEL = P / 'outbound-five-trained-v1'
PACKAGE = P / 'outbound-five-fixed-epoch1-v1'
SELECTION = P / 'fresh-policy-selection-v2/inputs.json'
SELECTED = [(3, 162), (4, 107), (5, 171), (6, 43), (8, 38)]
DATA_SHA256 = '765f160e1e07fbc2b9598f57b0f6ea14e2a4782c7b4bf383c20c9ea16b10b272'
MAP_SHA256 = 'fc8d693afb2acafc1e3b9e86d30a81c1f43099af21fbdb2f5b3d839148ed4896'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def parent_receipt():
    path = PARENT / 'receipt.json'; receipt = json.loads(path.read_text())
    expected = {'schema': 'puppybot.visual-control-pup.v2', 'weightsSHA256': '9c586f40ad6fc1a13a17f325cd3b33da5aca07e4790ee0922fd59049cd89f0d1',
                'epochs': 8, 'batch': 2, 'learningRateMicros': 700, 'checkpointEveryEpochs': 8,
                'sequenceMirrorAugmentation': True, 'carryCue': True, 'speedTransitionLossWeight': 1,
                'stopLossWeight': 5, 'actionCodec': 'joint-seven-v1', 'memoryWidth': 128,
                'imageSide': 84, 'taskFeedback': False, 'phaseSupervisionFromValidFrames': False,
                'memoryMapTargetsSHA256': 'c86e26e1db640e3c7436df95961f8e610d1812c49f5c1c7e8c9093bbcc5aae5a'}
    for key, value in expected.items():
        actual = receipt.get(key)
        if (actual is not value if isinstance(value, bool) else actual != value):
            raise ValueError(f'parent training property changed: {key}')
    for key, name in (('weightsSHA256', 'weights.bin'), ('binarySHA256', 'policy'), ('graphSHA256', 'model.pup')):
        if sha(PARENT / name) != receipt[key]:
            raise ValueError(f'parent file differs: {name}')
    kernels = receipt.get('kernels')
    if not isinstance(kernels, dict) or len(kernels) < 5:
        raise ValueError('parent kernel receipt incomplete')
    for name, digest in kernels.items():
        if Path(name).name != name or sha(PARENT / 'kernels' / name) != digest:
            raise ValueError('parent kernel differs')
    return receipt


def selection_design():
    data = json.loads(SELECTION.read_text()); design = data.get('design', {}); tasks = design.get('tasks')
    if (design.get('horizon') != 300 or design.get('actionSeconds') != .2 or design.get('cameraPitch') != 82 or
            design.get('gamesPerArmPerLevel') != 32 or not isinstance(tasks, list) or len(tasks) != 5):
        raise ValueError('selection design differs')
    rows = []
    for level, task in enumerate(tasks, 1):
        if task.get('name') != f'L{level}' or task.get('level') != level or len(task.get('rows', [])) != 32:
            raise ValueError('selection level differs')
        for index, row in enumerate(task['rows']):
            if row.get('index') != index or row.get('seed') != 7820000 + index:
                raise ValueError('selection seed/order differs')
            scene = Path(row['scene'])
            files = {}
            for name in ('case.json', 'environment.bin', 'layout.json'):
                path = scene / name; key = str(path)
                if key not in data['files'] or key not in data['sceneLinks']:
                    raise ValueError('selection input not recorded')
                target = data['sceneLinks'][key]
                if (target == 'regular-file' and (path.is_symlink() or not path.is_file()) or
                    target != 'regular-file' and (not path.is_symlink() or str(path.resolve(strict=True)) != target)):
                    raise ValueError('selection input link changed')
                digest = sha(path)
                if digest != data['files'][key]:
                    raise ValueError('selection input content changed')
                files[name] = digest
            rows.append({'level': level, 'index': index, 'seed': row['seed'], 'layout': row['layout'],
                         'variant': row['variant'], 'scene': str(scene), 'files': files})
    if len(rows) != 160:
        raise ValueError('wrong number of selection games')
    return rows


def design():
    receipt = parent_receipt()
    return {'schema': 'puppybot.outbound-five-fixed-design.v1',
            'parent': str(PARENT), 'parentWeightsSHA256': receipt['weightsSHA256'],
            'parentReceiptSHA256': sha(PARENT / 'receipt.json'),
            'dataset': str(AGGREGATE), 'datasetShape': [1029, 933, 300],
            'datasetSHA256': DATA_SHA256, 'mapSHA256': MAP_SHA256,
            'selectedTeacherEpisodes': [{'index': i, 'firstConsumptionAction': cutoff} for i, cutoff in SELECTED],
            'maskedEpisodeRange': [928, 933], 'trainerBuild': str(TRAINER),
            'training': {'seed': 7120000, 'epochs': 1, 'checkpointEveryEpochs': 1, 'batch': 2,
                         'learningRateMicros': 100, 'categorical': True, 'carryCue': True,
                         'mirrorAugment': True, 'transitionWeightOne': True, 'memoryMap': True,
                         'phaseFromValid': False, 'eventAux': False, 'poseAux': False, 'targetAux': False,
                         'searchCue': False, 'focusCopies': 0},
            'modelOutput': str(MODEL), 'selectionPackage': str(PACKAGE),
            'checkpointRule': 'fixed epoch-1; never validation-selected weights',
            'evaluation': {'selectionManifest': str(SELECTION), 'selectionManifestSHA256': sha(SELECTION),
                           'selectionRows': selection_design(), 'horizon': 300, 'cameraPitch': 82,
                           'controls': ['student-s1', 'fixed epoch-1 candidate', 'exploring teacher'],
                           'seedsPerLevel': list(range(7820000, 7820032)),
                           'loopMetric': 'pose20-final-inclusive-v2 reconstructed independently for every complete game',
                           'monitoring': 'new reviewed catalog-aware GPU/disk supervisor; preserve failed outputs',
                           'metrics': ['complete virtual pickup and delivery per game', 'first virtual pickup L3',
                                       'past-doorway delivery L4', 'back-and-forth action share',
                                       'longer search-return loop indicator', 'deliveries per minute'],
                           'goalThresholds': {'completedGameMinimumPerLevel': 29, 'gamesPerLevel': 32,
                                              'firstPickupL3Minimum': 29, 'doorwayDeliveryMinimumShare': .8,
                                              'backForthActionShareStrictlyLessThan': .02,
                                              'deliveriesPerMinuteAtLeastTeacherPerLevel': True,
                                              'requireReliabilityWithoutSacrifice': True},
                           'checkpointSelection': 'none; fixed before training',
                           'promotion': 'none; independently reviewed further selection required'},
            'scope': 'one exploratory warm-start training run and previously-used training-family selection; '
                     'no training execution, held-out, independent ancestry or physical claim'}


if __name__ == '__main__':
    print(json.dumps(design(), sort_keys=True, indent=2, allow_nan=False))
