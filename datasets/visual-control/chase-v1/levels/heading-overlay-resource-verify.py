#!/usr/bin/env python3
"""Recheck recorded full-overlay resource evidence without changing data."""
import importlib.util
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'search-dagger-heading'
ORIGINAL = P / 'search-dagger-l4-matched/data'
spec = importlib.util.spec_from_file_location('overlay_resource_source', S / 'heading-reflink-overlay.py')
overlay = importlib.util.module_from_spec(spec); spec.loader.exec_module(overlay)


def physical_maps():
    return {name: [list(span) for span in overlay.physical_map(ORIGINAL / name)] for name in ('data.bin', 'map.bin')}


def valid_extent(value):
    return (isinstance(value, dict) and set(value) == {'total', 'exclusive', 'shared'} and
            all(type(value[key]) is int for key in value) and value['total'] > 0 and
            0 <= value['exclusive'] <= value['total'] and 0 <= value['shared'] <= value['total'])


def collect():
    maps = physical_maps(); evidence = {}; hashes = {}
    for arm in ('control', 'treatment'):
        path = OUTPUT / f'resource-{arm}.json'; row = json.loads(path.read_text())
        if (row.get('sourcePhysicalMapBefore') != maps or row.get('sourcePhysicalMapAfter') != maps or
                any(type(row.get(key)) is not int or row[key] < 32 * 1024**3 for key in ('freeBefore', 'freeAfter'))):
            raise ValueError(f'overlay resource maps or free-space evidence differ: {arm}')
        for category in ('sourceExtentsBefore', 'sourceExtentsAfter', 'targetExtents'):
            extents = row.get(category)
            if (not isinstance(extents, dict) or set(extents) != {'data.bin', 'map.bin'} or
                    not all(valid_extent(value) for value in extents.values())):
                raise ValueError(f'invalid overlay extent evidence: {arm}')
        if row['targetExtents']['data.bin']['shared'] <= 0:
            raise ValueError(f'no shared data recorded for {arm}')
        evidence[arm] = row; hashes[arm] = overlay.digest(path)
    if physical_maps() != maps: raise ValueError('source physical maps changed during resource audit')
    return evidence, hashes


def verify_ready(ready):
    evidence, hashes = collect()
    if ready.get('resourceEvidence') != evidence or ready.get('resourceEvidenceSHA256') != hashes:
        raise ValueError('overlay resource evidence differs from pair receipt')
