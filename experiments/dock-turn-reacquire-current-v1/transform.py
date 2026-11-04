#!/usr/bin/env python3
"""Apply the bounded wait to the current simulator's settled guard."""
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    'dock_turn_reacquire', HERE.parent / 'dock-turn-reacquire-v1/transform.py')
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)

GUARD = '''    // Wait for the already-authorized yaw to settle; its retained lowering
    // target needs a fresh, stable and unchanged camera observation.
    if ps_case_camera && (!ps_dock_fresh() || ps_dock_stable < 3 || ps_case_dock_changed()) {
        return ps_case_fail("box observation lost or changed while turning above container");
    }
'''


def transform(source):
    return candidate.transform(candidate.once(source, GUARD, ''))
