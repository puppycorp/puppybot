#!/usr/bin/env python3
"""Episode-level scores must retain failures and penalize early termination."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'flex/exploration'))
from episodes import module, released_inside, summarize
from policy import sha256


def held_is_not_delivered():
    class Geometry:
        @staticmethod
        def contained(obj, definition, container):
            assert obj['id'] != 'outside'

    state = dict(gripper=dict(held=True, body=8), case=dict(container={},
        objects=[dict(id='released', body=7), dict(id='held-inside', body=8), dict(id='outside', body=9)]))
    assert released_inside(state, {}, Geometry) == ['released']
    state['gripper']['held'] = False
    assert released_inside(state, {}, Geometry) == ['released', 'held-inside']


def endpoints(directory):
    result = json.loads((directory/'summary.json').read_text())
    plan = json.loads((directory/'experiment-plan.json').read_text())
    assert result['complete'] and result['allAuditsPassed']
    expected = {(seed, mode, repeat) for seed in plan['seeds'] for mode in plan['policies']
                for repeat in range(1, plan['repeats']+1)}
    assert {(r['seed'], r['policy'], r['repeat']) for r in result['rows']} == expected
    manifest = json.loads((directory/'source-manifest.json').read_text())
    assert all(sha256(path) == digest for path, digest in manifest.items())
    source = next(Path(name) for name in manifest if name.endswith('/flex/tests/sim-cases.py'))
    geometry = module('retained_endpoint_geometry', source)
    checked = []
    for row in result['rows']:
        run = directory/'episodes'/f'{row["seed"]}-{row["policy"]}-{row["repeat"]}'
        path = run/'trace.jsonl'
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size-40000))
            lines = stream.read().splitlines()
        state = next(json.loads(line) for line in reversed(lines) if line.startswith(b'{') and line.endswith(b'}'))
        definition = json.loads((directory/'scenes'/str(row['seed'])/'case.json').read_text())
        inside = released_inside(state, definition, geometry)
        audit = json.loads((run/'audit.json').read_text())
        assert set(inside) == set(audit['independentlyContained']) and len(inside) == row['delivered']
        if row['taskPassed']:
            assert len(inside) == len(definition['objects']) and not state['gripper']['held']
        checked.append(dict(seed=row['seed'], policy=row['policy'], releasedSettled=len(inside), heldAtEnd=state['gripper']['held']))
    receipt = dict(passed=True, sourceHashesUnchanged=True, fullTrialMatrix=True,
                   heldPayloadsExcluded=True, endpointScoresUnchanged=True, episodes=checked)
    (directory/'endpoint-verification.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path)
    args = parser.parse_args()
    held_is_not_delivered()
    rows = [dict(policy='heuristic', taskPassed=True, delivered=6, actionSeconds=100., wallSeconds=20.),
            dict(policy='heuristic', taskPassed=False, delivered=2, actionSeconds=10., wallSeconds=2.),
            dict(policy='yolo', taskPassed=False, delivered=3, actionSeconds=150., wallSeconds=30.)]
    plan = dict(policies=['heuristic', 'yolo'], seeds=[1, 2], repeats=1, steps=10000)
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary)
        summarize(output, rows, plan)
        result = json.loads((output/'summary.json').read_text())
        assert not result['complete']
        heuristic, yolo = result['policies']['heuristic'], result['policies']['yolo']
        assert heuristic['successRate'] == .5 and heuristic['episodes'] == 2
        assert heuristic['meanCappedCompletionSeconds'] == 150 and yolo['meanCappedCompletionSeconds'] == 200
        assert heuristic['deliveriesPerBudgetMinute'] == 60*8/300
        assert yolo['deliveriesPerBudgetMinute'] == 60*3/200
        assert heuristic['completedActionSeconds'] == [100.] and yolo['completedActionSeconds'] == []
        assert len((output/'summary.csv').read_text().splitlines()) == 4
    print('Episode scores passed: held payloads excluded, all failures retained, incomplete batch identified and early failures charged the full action budget')
    if args.artifacts:
        endpoints(args.artifacts.resolve())


if __name__ == '__main__':
    main()
