#!/usr/bin/env python3
"""Stage opt-in image-stall search transfer in a copied hybrid simulator client."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('archived client differs from expected anchor')
    return source.replace(old, new, 1)


def transform(source):
    source = once(source, 'import "progress-guard.flex";',
                  'import "progress-guard.flex";\nimport "visual-stall.flex";')
    source = once(source, 'global pc_search_requests = -1;',
                  'global pc_search_requests = -1;\n'
                  'global pc_visual_recovery_enabled = 0;\n'
                  'global pc_visual_recovery_state = 0;\n'
                  'global pc_visual_recovery_reason = 0;\n'
                  'global pc_visual_recovery_outcome = 0;\n'
                  'global pc_visual_recovery_trigger_action = -1;')
    source = once(source, 'fn pc_pin_inputs(simulator, model, case_path, environment) {',
                  '''// The client has already validated the current driving frame and echo.
// A repeated image is a suspicion, not evidence of free floor or stopping.
fn pc_visual_recovery_check(actions) {
    let frame = vc_json_int(pc_state, "cameraFrame", 0);
    let tick = vc_json_int(pc_state, "totalSteps", 0);
    let drive = pj_get(pc_state, "driveCommand");
    let left = pj_value(pj_index(drive, 0)); let right = pj_value(pj_index(drive, 1));
    let valid = !pj_error && frame == tick && pj_boolean(pc_state, "cameraDriving") && pj_boolean(pc_state, "cameraStill") && pj_boolean(pc_state, "imageValid");
    if !vs_observe(pc_visual_recovery_state, ve_image, ve_image_bytes, valid, tick, left, right) { return 0; }
    pc_visual_recovery_reason = vs_reason(pc_visual_recovery_state);
    pc_visual_recovery_trigger_action = actions;
    if pc_visual_recovery_reason == 1 {
        // This frame is never sent to the actor, so retain it separately for
        // the saved trigger audit. Exclusive creation preserves prior data.
        let fd = syscall(2, vc_path(pc_output, "visual-trigger.rgb"), 0x800c1, 384, 0, 0, 0);
        vc_require(fd >= 0, "cannot create visual trigger image");
        let error = pl_write(fd, ve_image, ve_image_bytes); syscall(3, fd, 0, 0, 0, 0, 0);
        vc_require(!error, "cannot write visual trigger image");
    }
    return pc_visual_recovery_reason;
}
fn pc_pin_inputs(simulator, model, case_path, environment) {''')
    source = once(source, 'fn pc_result(actions, handoff, terminal, nav_limit, poll_limit, trace_sha) {',
                  '''fn pc_visual_recovery_outcome_text() {
    if pc_visual_recovery_outcome == 1 { return "search_started_unverified"; }
    if pc_visual_recovery_outcome == 2 { return "target_handoff_unverified"; }
    if pc_visual_recovery_outcome == 3 { return "transfer_did_not_start"; }
    if pc_visual_recovery_outcome == 4 { return "invalid_observation"; }
    return "not_triggered";
}
fn pc_result(actions, handoff, terminal, nav_limit, poll_limit, trace_sha) {''')
    source = once(source, '    if pc_search_enabled { pl_text(b, ",\\\"searchFallbackStarted\\\":"); pj_bool_text(b, pc_search_started); }',
                  '''    if pc_search_enabled { pl_text(b, ",\\\"searchFallbackStarted\\\":"); pj_bool_text(b, pc_search_started); }
    if pc_visual_recovery_enabled { pl_text(b, ",\\\"visualRecoveryReason\\\":"); pl_int(b, pc_visual_recovery_reason);
        pl_text(b, ",\\\"visualRecoveryTriggerAction\\\":"); pl_int(b, pc_visual_recovery_trigger_action);
        pl_text(b, ",\\\"visualRecoveryOutcome\\\":"); pj_text(b, pc_visual_recovery_outcome_text()); }''')
    source = once(source, '    vc_require(!(pc_rescan_enabled && pc_search_enabled), "search fallback and guarded rescan cannot both be enabled");',
                  '''    vc_require(!(pc_rescan_enabled && pc_search_enabled), "search fallback and guarded rescan cannot both be enabled");
    value = pl_environment(argc, argv, "PUPPYBOT_VISUAL_SEARCH_RECOVERY");
    if value { vc_require(pl_equal(value, "0") || pl_equal(value, "1"), "invalid visual search recovery opt-in"); pc_visual_recovery_enabled = pl_equal(value, "1"); }
    vc_require(!pc_visual_recovery_enabled || pc_search_enabled, "visual recovery requires search fallback");''')
    source = once(source, '    pc_journal = syscall(2, vc_path(pc_output, "physical-agent.jsonl"),',
                  '''    if pc_visual_recovery_enabled { pc_visual_recovery_state = alloc(48); let previous_image = alloc(ve_image_bytes);
        vc_require(vs_init(pc_visual_recovery_state, previous_image, ve_image_bytes, 5), "cannot initialize visual recovery"); }
    pc_journal = syscall(2, vc_path(pc_output, "physical-agent.jsonl"),''')
    source = once(source, '    while actions < nav_limit && !handoff {',
                  '    let visual_abort = 0;\n    while actions < nav_limit && !handoff && !pc_search_started && !visual_abort {')
    source = once(source, '        if !handoff {\n            pc_record_input();',
                  '''        if !handoff && pc_visual_recovery_enabled {
            let reason = pc_visual_recovery_check(actions);
            if reason == 1 {
                handoff = pc_search_fallback();
                if handoff { pc_visual_recovery_outcome = 2; }
                else if pc_search_started { pc_visual_recovery_outcome = 1; }
                else { pc_visual_recovery_outcome = 3; visual_abort = 1; }
            } else if reason { pc_visual_recovery_outcome = 4; visual_abort = 1; }
        }
        if !handoff && !pc_search_started && !visual_abort {
            pc_record_input();''')
    source = once(source, '    if pc_search_enabled && !handoff && actions == nav_limit {',
                  '    if pc_search_enabled && !handoff && !pc_search_started && !visual_abort && actions == nav_limit {')
    return source
