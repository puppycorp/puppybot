#!/usr/bin/env python3
"""Preserve old collector plan and re-audit its documentation-only revision."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / 'build/flex/sim/levels-v2/pitch82'
OLD = BASE / 'parent-route-collector-plan-v1/plan.json'
OLD_RECEIPT = OLD.parent / 'lineage-audit.json'
OUTPUT = BASE / 'parent-route-collector-plan-v2'
DOC = ROOT / 'diary/128-parent-retention-feasibility.md'
OLD_SHA = '54acceb5e71859e1b6eb010dca66528733a317b8cbb100e5318cf95ec368604d'
OLD_DOC_SHA = '2a9995fe55580e609b60f03d1d027ee93c14f1b2270f8e7231ab945b21e9781b'
NEW_DOC_SHA = '626af37476903c61ee82f01fa75ed250fa0f39c0277ddfed564251b6de9e3a2c'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


lineage = load('parent_plan_v2_lineage', ROOT / 'experiments/parent-route-collector-plan-v1/audit.py')


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')


def revise():
    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise FileExistsError('revised plan directory already exists; retain it')
    if lineage.sha(OLD) != OLD_SHA or lineage.sha(DOC) != NEW_DOC_SHA:
        raise ValueError('original plan or documented change differs')
    prefix, separator, suffix = DOC.read_bytes().partition(b'\n\nThe current diverse generator permits')
    if not separator or not suffix or hashlib.sha256(prefix + b'\n').hexdigest() != OLD_DOC_SHA:
        raise ValueError('prior documentation is not the exact retained prefix')
    old = json.loads(OLD.read_text()); old_receipt = json.loads(OLD_RECEIPT.read_text())
    if (old['inputSHA256'].get(str(DOC)) != OLD_DOC_SHA or
            old_receipt.get('planSHA256') != OLD_SHA or old_receipt.get('status') != 'lineage_plan_only'):
        raise ValueError('original plan receipt differs')
    new = copy.deepcopy(old); new['inputSHA256'][str(DOC)] = NEW_DOC_SHA
    audit = lineage.audit(new)
    if audit.get('status') != 'lineage_plan_only' or lineage.sha(OLD) != OLD_SHA or lineage.sha(DOC) != NEW_DOC_SHA:
        raise ValueError('revised lineage or source changed')
    OUTPUT.mkdir()
    write_new(OUTPUT / 'plan.json', new)
    plan_hash = lineage.sha(OUTPUT / 'plan.json')
    receipt = {**audit, 'planSHA256': plan_hash, 'auditSourceSHA256': lineage.sha(Path(lineage.__file__)),
               'oldPlanSHA256': OLD_SHA, 'oldReceiptSHA256': lineage.sha(OLD_RECEIPT),
               'changedPath': str(DOC), 'oldDocumentSHA256': OLD_DOC_SHA, 'newDocumentSHA256': NEW_DOC_SHA,
               'scope': 'separately audited documentation-only plan revision; original plan remains unchanged'}
    write_new(OUTPUT / 'lineage-audit.json', receipt)
    if lineage.audit(json.loads((OUTPUT / 'plan.json').read_text())) != audit:
        raise ValueError('published revised lineage differs')
    if lineage.sha(OLD) != OLD_SHA or lineage.sha(DOC) != NEW_DOC_SHA:
        raise ValueError('original plan or documentation changed after revision')
    os.chmod(OUTPUT / 'plan.json', 0o444); os.chmod(OUTPUT / 'lineage-audit.json', 0o444)
    return receipt


if __name__ == '__main__':
    raise SystemExit('Disabled pending review; never overwrite the original plan.')
