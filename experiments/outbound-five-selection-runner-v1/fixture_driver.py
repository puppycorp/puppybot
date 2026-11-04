#!/usr/bin/env python3
"""Synthetic fresh-process monitor/final fixture; no GPU or model is used."""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('outbound_selection_fixture', HERE / 'runner.py')
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
mode, root, output, monitored, manifest = sys.argv[1:]
root, output, monitored, manifest = map(Path, (root, output, monitored, manifest))
frozen = json.loads(manifest.read_text())
r.OUTPUT, r.MONITOR, r.MANIFEST = output, monitored, manifest
r.verify = lambda: frozen
r.verify_saved = lambda _: json.loads((output / 'report.json').read_text())
old_install = r.strict_inventory.install
r.strict_inventory.install = lambda monitor, output, monitored, manifest, verify: old_install(
    monitor, output, monitored, manifest, verify, base_dir=root)
mon = r.base.monitor
registrar = SimpleNamespace(verify=lambda: frozen)
expected = r.strict_inventory.postrun.expected_catalogs(frozen)
code = ('import json,pathlib,sys; root=pathlib.Path(sys.argv[1]); root.mkdir();'
        'f=json.loads(sys.argv[2]); e=json.loads(sys.argv[3]);'
        '[(p.parent.mkdir(parents=True,exist_ok=True),p.symlink_to(t,target_is_directory=True)) '
        'for n,t in e.items() for p in [root/n]];'
        '(root/"inputs.json").write_text(json.dumps(f));'
        '(root/"report.json").write_text(json.dumps({"status":"diagnostic_only"}))')
r.python_call = lambda function, *args: [sys.executable, '-I', '-c', code, str(output),
                                         json.dumps(frozen), json.dumps(expected)]
with (mock.patch.object(mon, 'load', return_value=registrar), mock.patch.object(mon, 'baseline'),
      mock.patch.object(mon, 'sample_disk'), mock.patch.object(mon, 'verify_logs'),
      mock.patch.object(mon, 'require_disk'),
      mock.patch.object(mon.telemetry, 'sample', return_value={'freeBytes': 8 * 1024**3})):
    if mode == 'worker':
        r.monitor_worker(monitored)
        print(json.dumps({'worker': 'completed', 'catalogLinks': len(json.loads((monitored / 'evidence.json').read_text())['files']['links'])}))
    elif mode == 'final':
        evidence_sha = mon.base.sha(monitored / 'evidence.json')
        r.final_check(monitored, evidence_sha)
    else:
        raise ValueError('unknown fixture mode')
