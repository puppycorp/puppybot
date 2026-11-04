#!/usr/bin/env python3
"""CPU-test-only fresh-process monitor driver; never runs a simulator."""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


adapter = load('fixture_adapter', HERE / 'adapter.py')
monitor = load('fixture_monitor', ROOT / 'experiments/l5-steering-hysteresis-v1/monitor.py')


def main():
    role, root, output, monitored, manifest = sys.argv[1:6]
    root, output, monitored, manifest = map(Path, (root, output, monitored, manifest))
    verify = lambda: json.loads(manifest.read_text())
    monitor.OUTPUT = output; monitor.MONITOR = monitored; monitor.MANIFEST = manifest
    adapter.install(monitor, output, monitored, manifest, verify, base_dir=root)
    monitor.REGISTER = manifest
    monitor.load = lambda *args: SimpleNamespace(verify=verify)
    monitor.verify_saved = lambda frozen: json.loads((output / 'report.json').read_text())
    if role == 'worker':
        expected = adapter.postrun.expected_catalogs(verify())
        code = ('import json,pathlib,sys;root=pathlib.Path(sys.argv[1]);root.mkdir();'
                'f=json.loads(sys.argv[2]);e=json.loads(sys.argv[3]);'
                '[(p.parent.mkdir(parents=True,exist_ok=True),p.symlink_to(t,target_is_directory=True)) '
                'for n,t in e.items() for p in [root/n]];'
                '(root/"inputs.json").write_text(json.dumps(f));'
                '(root/"report.json").write_text(json.dumps({"status":"diagnostic_only"}))')
        monitor.worker_command = lambda: [sys.executable, '-B', '-I', '-c', code, str(output),
                                           json.dumps(verify()), json.dumps(expected)]
        # Resource telemetry/registration are intentionally mocked in this fixture.
        monitor.baseline = lambda log: None
        monitor.sample_disk = lambda *args: None
        monitor.verify_logs = lambda *args: None
        monitor.require_disk = lambda *args: None
        monitor.telemetry.sample = lambda *args: {'freeBytes': 8 * 1024 ** 3}
        monitor._worker(monitored)
        print(json.dumps({'worker': 'completed', 'adapterInstalled': True}))
    elif role == 'final':
        result = monitor.final_check(monitored, monitor.base.sha(monitored / 'evidence.json'))
        print(json.dumps(result, sort_keys=True))
    else:
        raise ValueError('unknown fixture role')


if __name__ == '__main__':
    main()
