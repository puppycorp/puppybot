#!/usr/bin/env python3
"""Fixed draft design for a two-arm, 12-game L5 simulator diagnostic.

No scene generation, GPU work, registration, or held-out access occurs here.
A separately reviewed inventory verifier and executor are required before use.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
SCENES = ROOT / 'build/flex/sim/expanded-rooms-v1/scenes'
OUTPUT = P / 'l5-steering-kick-diagnostic-v1'
BUILD = P / 'l5-steering-kick-build-v1'
MODEL = P / 'search-dagger-heading/models/heading-epoch8-pair/treatment'


def design():
    rows = []
    for layout in (13, 15, 17):
        for variant in range(4):
            index = len(rows)
            rows.append({'index': index, 'layout': layout, 'variant': variant,
                         'seed': 6800100 + index, 'scene': str(SCENES / str(layout) / str(variant))})
    return {'schema': 'puppybot.l5-steering-kick-draft.v1', 'status': 'draft_not_registered',
            'conditions': rows, 'arms': ['control', 'intervention'], 'episodesPerArm': 12,
            'horizon': 300, 'cameraPitch': 82, 'level': 5, 'model': str(MODEL),
            'trigger': {'firstActionSteeringAtMost': -.5, 'firstActionSpeedAtMost': -.8,
                        'maxActions': 3, 'stopOnExistingCarryCue': True},
            'screen': {'minimumTriggered': 6, 'minimumAdditionalConsumedByAction200': 3,
                       'minimumDeliveryDifference': 0, 'maximumAdditionalMostlyBackForthGames': 0},
            'denominator': 'all 12 matched games including no-ops and misses',
            'prerequisite': 'freeze exact binary/model/runtime/source/scene identities before any run; independently verify seeds against recorded historical inventories and non-heldout scene roles; verify clean source snapshots and paired initial bytes; require dedicated bounded resource monitor and reviewed executor',
            'scope': 'exploratory training-family simulator comparison; scenes are previously used, unknown pretraining ancestry; no held-out, physical or actor-execution attestation'}


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review, seed inventory and monitored executor.')
