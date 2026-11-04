#!/usr/bin/env python3
"""Instrument private simulator copies for a one-shot dock observation fault."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unexpected simulator source')
    return source.replace(old, new, 1)


def transform(case, dock, duration, candidate):
    if duration not in (0, 10, 60) or type(candidate) is not bool:
        raise ValueError('unexpected probe mode')
    # Immediate-stop control has no wait state; define it only for telemetry.
    if not candidate:
        case = once(case, 'global ps_case_drop_turning = 0;', '''global ps_case_drop_turning = 0;
global ps_case_drop_reacquire_started = -1;''')
    case = once(case, 'global ps_case_drop_turning = 0;', f'''global ps_case_drop_turning = 0;
global ps_turn_probe_duration = {duration};
global ps_turn_probe_at = -1;
global ps_turn_probe_eligible = 0;
global ps_turn_probe_pre_stable = 0;
global ps_turn_probe_pre_frame = -1;
global ps_turn_probe_masked = 0;
global ps_turn_probe_lower_at = -1;''')
    case = once(case, 'fn ps_case_reset() {', '''fn ps_case_reset() {
    ps_turn_probe_at = -1; ps_turn_probe_eligible = 0; ps_turn_probe_pre_stable = 0; ps_turn_probe_pre_frame = -1;
    ps_turn_probe_masked = 0; ps_turn_probe_lower_at = -1;''')
    # ps_pickup_settled is stateful: insert after its existing sole call.
    before, marker, turn = case.partition('fn ps_case_drop_turn_update() {')
    if not marker:
        raise ValueError('missing turn function')
    turn, end, after = turn.partition('fn ps_case_drop_clearance(')
    if not end:
        raise ValueError('missing turn function boundary')
    turn = once(turn, '''    if !ps_pickup_settled() { return 1; }''', '''    if !ps_pickup_settled() { return 1; }
    if ps_case_camera && ps_turn_probe_at < 0 {
        ps_turn_probe_at = ps_total;
        ps_turn_probe_pre_stable = ps_dock_stable; ps_turn_probe_pre_frame = ps_dock_seen;
        ps_turn_probe_eligible = ps_dock_fresh() && ps_dock_stable >= 3 && !ps_case_dock_changed();
        if ps_turn_probe_duration && ps_turn_probe_eligible { ps_dock_valid = 0; ps_turn_probe_masked = ps_turn_probe_masked + 1; }
    }''')
    case = before + marker + turn + end + after
    case = once(case, '''    if pr_apply(ps_app, 5, ps_pickup_targets, ps_time) { return ps_case_fail("cannot lower release arm pose after turning"); }''', '''    if ps_turn_probe_lower_at < 0 { ps_turn_probe_lower_at = ps_total; }
    if pr_apply(ps_app, 5, ps_pickup_targets, ps_time) { return ps_case_fail("cannot lower release arm pose after turning"); }''')
    case = once(case, '''    pl_text(b, ",\\\"reason\\\":"); pj_text(b, ps_case_reason);''', '''    pl_text(b, ",\\\"turnProbe\\\":{\\\"duration\\\":"); pl_int(b, ps_turn_probe_duration);
    pl_text(b, ",\\\"triggerTick\\\":"); pl_int(b, ps_turn_probe_at);
    pl_text(b, ",\\\"eligible\\\":"); pj_bool_text(b, ps_turn_probe_eligible);
    pl_text(b, ",\\\"preStable\\\":"); pl_int(b, ps_turn_probe_pre_stable);
    pl_text(b, ",\\\"preFrame\\\":"); pl_int(b, ps_turn_probe_pre_frame);
    pl_text(b, ",\\\"masked\\\":"); pl_int(b, ps_turn_probe_masked);
    pl_text(b, ",\\\"lowerTick\\\":"); pl_int(b, ps_turn_probe_lower_at);
    pl_text(b, ",\\\"turning\\\":"); pj_bool_text(b, ps_case_drop_turning);
    pl_text(b, ",\\\"waitTick\\\":"); pl_int(b, ps_case_drop_reacquire_started); pl_char(b, 125);
    pl_text(b, ",\\\"reason\\\":"); pj_text(b, ps_case_reason);''')
    dock = once(dock, '''    if !ps_rgb_sample() { ps_dock_valid = 0; return 0; }
    let found = ps_dock_detect();''', '''    let suppressed = ps_turn_probe_at >= 0 && ps_turn_probe_eligible && ps_total - ps_turn_probe_at < ps_turn_probe_duration;
    if suppressed { ps_turn_probe_masked = ps_turn_probe_masked + 1; }
    if !ps_rgb_sample() { ps_dock_valid = 0; return 0; }
    if suppressed { ps_dock_valid = 0; ps_dock_stable = 0; return 0; }
    let found = ps_dock_detect();''')
    return case, dock
