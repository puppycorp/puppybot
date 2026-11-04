#!/usr/bin/env python3
"""Stage a simulator-only stop when visual-trigger evidence cannot be saved."""
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    'visual_search_recovery_transform', ROOT / 'experiments/visual-search-recovery-v1/transform.py')
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)


def transform(source):
    source = BASE.transform(source)
    source = BASE.once(source,
        '''        vc_require(fd >= 0, "cannot create visual trigger image");
        let error = pl_write(fd, ve_image, ve_image_bytes); syscall(3, fd, 0, 0, 0, 0, 0);
        vc_require(!error, "cannot write visual trigger image");''',
        '''        // A failed evidence write must not prevent the normal stop path.
        // Preserve any existing or partial file and do not start a transfer.
        if fd < 0 { return 3; }
        let error = pl_write(fd, ve_image, ve_image_bytes);
        let closed = syscall(3, fd, 0, 0, 0, 0, 0);
        if error || closed < 0 { return 3; }''')
    source = BASE.once(source,
        '    if pc_visual_recovery_outcome == 4 { return "invalid_observation"; }',
        '    if pc_visual_recovery_outcome == 4 { return "invalid_observation"; }\n'
        '    if pc_visual_recovery_outcome == 5 { return "trigger_evidence_unavailable"; }')
    source = BASE.once(source,
        '            } else if reason { pc_visual_recovery_outcome = 4; visual_abort = 1; }',
        '            } else if reason { pc_visual_recovery_outcome = 4;'
        ' if reason == 3 { pc_visual_recovery_outcome = 5; } visual_abort = 1; }')
    source = BASE.once(source,
        '    if pc_search_enabled { pc_search_intent(command, steering, speed, hold); }',
        '''    // After an evidence-write failure, do not let another disk write
    // prevent the stop request. This special stop has no intent-journal row.
    if pc_search_enabled && !(command == 3 && pc_visual_recovery_outcome == 5) { pc_search_intent(command, steering, speed, hold); }''')
    return source
