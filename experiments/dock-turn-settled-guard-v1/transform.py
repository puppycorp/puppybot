#!/usr/bin/env python3
"""Guard retained drop targets when a commanded arm turn has settled."""


def transform(source):
    needle = '''fn ps_case_drop_turn_update() {
    if !ps_gripper_held { return ps_case_fail("object lost while turning above container"); }
    if !ps_pickup_settled() { return 1; }
'''
    guard = needle + '''    // Wait for the already-authorized yaw to settle; its retained lowering
    // target needs a fresh, stable and unchanged camera observation.
    if ps_case_camera && (!ps_dock_fresh() || ps_dock_stable < 3 || ps_case_dock_changed()) {
        return ps_case_fail("box observation lost or changed while turning above container");
    }
'''
    if source.count(needle) != 1:
        raise ValueError('unexpected simulator turn update')
    return source.replace(needle, guard, 1)
