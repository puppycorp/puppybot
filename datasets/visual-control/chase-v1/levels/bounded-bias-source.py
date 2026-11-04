#!/usr/bin/env python3
"""Produce an isolated 30-action search-bias experiment source file.

This changes no worktree source. Both experiment arms use the same rebuilt
control binary and raw-logit path. Instrumentation counts the eligible steps
and the times bias changed the chosen class. This is experimental simulation
code; the carry flag is simulator task state rather than a physical sensor.
"""
from pathlib import Path


PICK = '''fn vx_pick(logits,action) {
    let bias=0;if !vx_carrying && ve_steps-vx_place_step>=vw_straight_after {bias=vc_number(vw_straight_bias,100);}
    let best=0;let top=pb_read_float(logits);let i=1;
    while i<7 {let v=pb_read_float(logits+i*4);if i==1 {v=f64_add(v,bias);}if f64_gt(v,top) {top=v;best=i;}i=i+1;}return vx_set(action,best);
}
'''

BOUNDED = '''fn vx_pick(logits,action) {
    let age=ve_steps-vx_place_step;let bias=0;if !vx_carrying && age>=vw_straight_after && age<vw_straight_after+30 {bias=vc_number(vw_straight_bias,100);vx_bias_eligible=vx_bias_eligible+1;}
    let unmodified=0;let prior=pb_read_float(logits);vc_require(f64_is_finite(prior),"nonfinite raw policy logits");let i=1;while i<7 {let v=pb_read_float(logits+i*4);vc_require(f64_is_finite(v),"nonfinite raw policy logits");if f64_gt(v,prior) {prior=v;unmodified=i;}i=i+1;}
    let best=0;let top=pb_read_float(logits);i=1;
    while i<7 {let v=pb_read_float(logits+i*4);if i==1 {v=f64_add(v,bias);}if f64_gt(v,top) {top=v;best=i;}i=i+1;}
    if bias && best!=unmodified {vx_bias_changed=vx_bias_changed+1;}return vx_set(action,best);
}
'''

RESULT = 'if vw_straight_bias {pl_text(b,",\\"straightBiasHundredths\\":");pl_int(b,vw_straight_bias);pl_text(b,",\\"straightAfterSteps\\":");pl_int(b,vw_straight_after);}'
MORE = 'pl_text(b,",\\"straightWindowSteps\\":30,\\"straightEligibleSteps\\":");pl_int(b,vx_bias_eligible);pl_text(b,",\\"straightChangedSteps\\":");pl_int(b,vx_bias_changed);'


def transform(source):
    replacements = [('global vx_noise_rng=1;', 'global vx_noise_rng=1;\nglobal vx_bias_eligible=0;\nglobal vx_bias_changed=0;'),
                    (PICK, BOUNDED),
                    ('vx_reaches=0;vx_jumps=0;', 'vx_bias_eligible=0;vx_bias_changed=0;vx_reaches=0;vx_jumps=0;'),
                    (RESULT, RESULT[:-1] + MORE + '}')]
    for old, new in replacements:
        if source.count(old) != 1:
            raise ValueError('unexpected source shape; refusing to patch')
        source = source.replace(old, new, 1)
    return source


def main():
    import sys
    if len(sys.argv) != 3:
        raise SystemExit('Usage: bounded-bias-source.py ORIGINAL_CHASE_FLEX NEW_CHASE_FLEX')
    source, destination = map(Path, sys.argv[1:])
    if destination.exists() or destination.is_symlink():
        raise ValueError('destination exists')
    destination.write_text(transform(source.read_text()))


if __name__ == '__main__':
    main()
