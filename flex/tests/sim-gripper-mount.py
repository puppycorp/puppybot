#!/usr/bin/env python3
"""Check the mechanical gripper mount against the original URDF end plate."""
import argparse
import importlib.util
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('views', Path(__file__).with_name('sim-views.py'))
views = importlib.util.module_from_spec(spec)
spec.loader.exec_module(views)


def check(directory):
    for name, steps in [('home', 1), ('moving', 120), ('turned', 240)]:
        state, camera, _ = views.capture(directory, name, '--camera', 'tcp', '--steps', steps, '--demo')
        views.check_mount(state, camera)
        assert not state['collision']['armBlocked'] and state['physicsFault'] == 0
    print('Gripper mount passed: fingers follow the original URDF TCP plate normal through joint and chassis motion; camera stays attached to the physical gripper')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT/'build/flex/puppybot-sim')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    views.simulation.BINARY = args.binary.resolve()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        check(args.output)
    else:
        with tempfile.TemporaryDirectory(prefix='gripper-mount-', dir=ROOT/'build/flex/sim') as temporary:
            check(Path(temporary))


if __name__ == '__main__':
    main()
