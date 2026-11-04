#!/usr/bin/env python3
"""Stage backwards-compatible terminal failure reporting for simulator peers."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unexpected source anchor')
    return source.replace(old, new, 1)


def simulator(source):
    source = once(source, 'fn ps_physical_observe() {', '''// Failure detail is a controller report, not proof of physical manipulation.
fn ps_physical_terminal_failure(b) {
    if ps_physical_ack == 5 && ps_case_stage == 13 {
        pl_text(b, ",\\\"collectorFailure\\\":");
        if ps_case_reason { pj_text(b, ps_case_reason); } else { pj_text(b, "collector failed"); }
    }
    return 0;
}
fn ps_physical_observe() {''')
    source = once(source, '    pl_text(b, "]}\\n"); if load64(b + 24) { return 0; }',
                  '    pl_char(b, 93); ps_physical_terminal_failure(b); pl_text(b, "}\\n"); if load64(b + 24) { return 0; }')
    return source


def client(source):
    source = once(source, 'global pc_rescan_stop_reason = 0;',
                  'global pc_rescan_stop_reason = 0;\nglobal pc_terminal_failure = 0;\nglobal pc_terminal_failure_invalid = 0;')
    source = once(source, 'fn pc_pin_inputs(simulator, model, case_path, environment) {', '''// Copy before the stop response replaces the JSON parser's input buffers.
// An absent field is an older peer or a terminal result without failure detail.
fn pc_remember_terminal_failure() {
    let node = pj_get(pc_state, "collectorFailure"); if !node { return 0; }
    if pj_kind(node) != 2 { pc_terminal_failure_invalid = 1; return 0; }
    let value = pj_value(node); let size = pj_count(node);
    // Bound escaped JSON output as well as the input, and reject embedded NUL.
    if !size || size > 128 || pl_size(value) != size { pc_terminal_failure_invalid = 1; return 0; }
    pc_terminal_failure = alloc(size + 1); vc_copy(pc_terminal_failure, value, size); store8(pc_terminal_failure + size, 0); return 1;
}
fn pc_pin_inputs(simulator, model, case_path, environment) {''')
    source = once(source, 'let b = alloc(32); let text = alloc(768); pl_builder(b, text, 768);',
                  'let b = alloc(32); let text = alloc(1536); pl_builder(b, text, 1536);')
    source = once(source, '    pl_text(b, ",\\\"stopCommandAcknowledged\\\":true,\\\"outcome\\\":\\\"unverified\\\",\\\"traceSHA256\\\":");',
                  '''    if pc_terminal_failure { pl_text(b, ",\\\"collectorFailure\\\":"); pj_text(b, pc_terminal_failure); }
    if pc_terminal_failure_invalid { pl_text(b, ",\\\"collectorFailureReportInvalid\\\":true"); }
    pl_text(b, ",\\\"stopCommandAcknowledged\\\":true,\\\"outcome\\\":\\\"unverified\\\",\\\"traceSHA256\\\":");''')
    source = once(source, '        if ack == 5 { terminal = 1; } polls = polls + 1; }',
                  '        if ack == 5 { terminal = 1; pc_remember_terminal_failure(); } polls = polls + 1; }')
    return source
