#!/usr/bin/env python3
"""Private bounded detector reacquisition after a release yaw settles."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unexpected saved simulator source')
    return source.replace(old, new, 1)


def transform(source):
    source = once(source, 'global ps_case_drop_turning = 0;', '''global ps_case_drop_turning = 0;
global ps_case_drop_reacquire_started = -1;
global ps_case_drop_reacquire_last = -1;''')
    source = once(source, 'fn ps_case_reset() {', '''fn ps_case_reset() {
    ps_case_drop_reacquire_started = -1; ps_case_drop_reacquire_last = -1;''')
    source = once(source, 'fn ps_case_drop_target(height) {', '''fn ps_case_drop_target(height) {
    ps_case_drop_reacquire_started = -1; ps_case_drop_reacquire_last = -1;''')
    old = '''fn ps_case_drop_turn_update() {
    if !ps_gripper_held { return ps_case_fail("object lost while turning above container"); }
    if !ps_pickup_settled() { return 1; }
    pb_copy(ps_pickup_targets, ps_case_drop_ticks, 32); ps_case_drop_turning = 0;'''
    new = '''fn ps_case_drop_turn_update() {
    if !ps_gripper_held { return ps_case_fail("object lost while turning above container"); }
    if ps_case_camera && ps_case_drop_reacquire_started >= 0 {
        // Check the deadline even if settlement later flaps. ps_total is the
        // simulation tick, not a wall-clock or physical safety watchdog.
        if ps_total <= ps_case_drop_reacquire_last || ps_total - ps_case_drop_reacquire_started >= 50 {
            return ps_case_fail("box observation reacquisition timed out after turn");
        }
        ps_case_drop_reacquire_last = ps_total;
        if ps_dock_fresh() && ps_dock_stable >= 3 && ps_case_dock_changed() {
            return ps_case_fail("box changed during observation reacquisition");
        }
    }
    if !ps_pickup_settled() { return 1; }
    if ps_case_camera {
        let ready = ps_dock_fresh() && ps_dock_stable >= 3;
        if ready && ps_case_drop_reacquire_started >= 0 && ps_dock_seen < ps_case_drop_reacquire_started { ready = 0; }
        if ready {
            if ps_case_dock_changed() { return ps_case_fail("box changed while turning above container"); }
        } else {
            if ps_case_drop_reacquire_started < 0 {
                ps_case_drop_reacquire_started = ps_total; ps_case_drop_reacquire_last = ps_total;
                // Require the detector's stability counter to build again
                // from subsequent observations, without altering its images.
                ps_dock_stable = 0;
            }
            return 1;
        }
    }
    ps_case_drop_reacquire_started = -1; ps_case_drop_reacquire_last = -1;
    pb_copy(ps_pickup_targets, ps_case_drop_ticks, 32); ps_case_drop_turning = 0;'''
    return once(source, old, new)
