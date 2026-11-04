#!/usr/bin/env python3
"""Instrument a copied dock-confirm simulator; no existing source is edited."""


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('unexpected source shape; refusing transformation')
    return text.replace(old, new, 1)


GLOBALS = '''// Diagnostic-only files; their absence never authorizes robot motion.
global ps_dock_diag_dir = 0;
global ps_dock_diag_survey_count = 0;
global ps_dock_diag_write_errors = 0;
global ps_dock_diag_searches = 0;
global ps_dock_diag_plan_count = 0;
global ps_dock_diag_plan_reason = 0;

fn ps_dock_diag_reason(reason) { if ps_dock_diag_dir { ps_dock_diag_plan_reason = reason; } return 0; }
fn ps_dock_diag_survey() {
    if !ps_dock_diag_dir || ps_case_stage != 18 || !ps_gripper_held { return 1; }
    let stem = h_cat3(ps_dock_diag_dir, "/survey-", h_int(ps_dock_samples));
    let error = pl_atomic_file(h_cat(stem, ".rgb"), ps_brick_rgb, 640 * 480 * 3);
    if error || !ps_brick_metadata(stem) { ps_dock_diag_write_errors = ps_dock_diag_write_errors + 1; }
    ps_dock_diag_survey_count = ps_dock_diag_survey_count + 1; return 1;
}
fn ps_dock_diag_candidate(index, goal, planned) {
    if !ps_dock_diag_dir { return 1; }
    ps_dock_diag_plan_count = ps_dock_diag_plan_count + 1;
    let text = alloc(1024); let b = alloc(32); pl_builder(b, text, 1024);
    pl_text(b, "{\\"schema\\":\\"puppybot.dock-viewpoint-diagnostic.v1\\",\\"step\\":"); pl_int(b, ps_total);
    pl_text(b, ",\\"search\\":"); pl_int(b, ps_dock_diag_searches); pl_text(b, ",\\"index\\":"); pl_int(b, index);
    pl_text(b, ",\\"goal\\":["); let i = 0; while i < 3 { if i { pl_char(b, 44); } pl_float(b, load64(goal + i * 8)); i = i + 1; }
    pl_text(b, "],\\"planned\\":"); pj_bool_text(b, planned); pl_text(b, ",\\"reason\\":"); pl_int(b, ps_dock_diag_plan_reason);
    pl_text(b, ",\\"expanded\\":"); pl_int(b, ps_nav_expanded); pl_text(b, "}\\n");
    let stem = h_cat3(ps_dock_diag_dir, "/search-", h_int(ps_dock_diag_searches));
    let path = h_cat3(stem, "-candidate-", h_int(index));
    if load64(b + 24) || pl_atomic_file(h_cat(path, ".json"), text, load64(b + 8)) { ps_dock_diag_write_errors = ps_dock_diag_write_errors + 1; }
    syscall(11, text, 1024, 0, 0, 0, 0); syscall(11, b, 32, 0, 0, 0, 0); return 1;
}
'''


def transform(main, dock, search, nav):
    if 'ps_dock_diag_dir' in dock or 'PUPPYBOT_DOCK_DIAG_DIRECTORY' in main:
        raise ValueError('source already instrumented')
    dock = once(dock, 'fn ps_dock_reset() {', GLOBALS + '\nfn ps_dock_reset() {')
    dock = once(dock, '    let found = ps_dock_detect(); if !found { ps_dock_stable = 0; }',
        '    ps_dock_diag_survey();\n    let found = ps_dock_detect(); if !found { ps_dock_stable = 0; }')
    dock = once(dock, '    return pl_text(b, "]}");\n}',
        '    pl_char(b, 93); if ps_dock_diag_dir { pl_text(b, ",\\"surveyDiagnostic\\":{\\"count\\":"); pl_int(b, ps_dock_diag_survey_count); pl_text(b, ",\\"planCount\\":"); pl_int(b, ps_dock_diag_plan_count); pl_text(b, ",\\"writeErrors\\":"); pl_int(b, ps_dock_diag_write_errors); pl_text(b, "}"); }\n    return pl_text(b, "}");\n}')
    main = once(main, '    let confirm = pl_environment(argc, argv, "PUPPYBOT_DOCK_CONFIRM");',
        '    ps_dock_diag_dir = pl_environment(argc, argv, "PUPPYBOT_DOCK_DIAG_DIRECTORY");\n'
        '    let confirm = pl_environment(argc, argv, "PUPPYBOT_DOCK_CONFIRM");')
    search = once(search, '        ps_dock_search_index = 0; ps_dock_search_started = ps_total; ps_dock_search_hint = 0; ps_dock_search_view_start = 0;',
        '        if ps_dock_diag_dir { ps_dock_diag_searches = ps_dock_diag_searches + 1; }\n'
        '        ps_dock_search_index = 0; ps_dock_search_started = ps_total; ps_dock_search_hint = 0; ps_dock_search_view_start = 0;')
    search = once(search,
        '        if ps_nav_plan(load64(ps_dock_search_goal), load64(ps_dock_search_goal + 8), load64(ps_dock_search_goal + 16)) {',
        '        let planned = ps_nav_plan(load64(ps_dock_search_goal), load64(ps_dock_search_goal + 8), load64(ps_dock_search_goal + 16));\n'
        '        if ps_dock_diag_dir { ps_dock_diag_candidate(ps_dock_search_index - 1, ps_dock_search_goal, planned); }\n'
        '        if planned {')
    nav = once(nav, 'fn ps_nav_plan(x, y, heading) {\n',
        'fn ps_nav_plan(x, y, heading) {\n    if ps_dock_diag_dir { ps_dock_diag_plan_reason = 0; }\n')
    nav = once(nav,
        '    if ps_nav_heading_free() { let cell = ps_nav_cell(x, y); if cell < 0 || load8(ps_nav_map + cell) { return 0; } }\n'
        '    else if !ps_nav_clear(x, y, heading) { return 0; }\n'
        '    pb_zero(ps_nav_nodes, ps_nav_capacity * 80); let start = ps_nav_index(ps_pose_x(), ps_pose_y(), ps_pose_heading()); if start < 0 { return 0; }',
        '    if ps_nav_heading_free() { let cell = ps_nav_cell(x, y); if cell < 0 { return ps_dock_diag_reason(1); } if load8(ps_nav_map + cell) { return ps_dock_diag_reason(2); } }\n'
        '    else if !ps_nav_clear(x, y, heading) { return ps_dock_diag_reason(3); }\n'
        '    pb_zero(ps_nav_nodes, ps_nav_capacity * 80); let start = ps_nav_index(ps_pose_x(), ps_pose_y(), ps_pose_heading()); if start < 0 { return ps_dock_diag_reason(4); }')
    nav = once(nav, '    ps_nav_searching = 0; if found < 0 { return 0; }',
        '    ps_nav_searching = 0; if found < 0 { return ps_dock_diag_reason(5); }')
    nav = once(nav, '        if ps_nav_path_count >= 2048 { return 0; }',
        '        if ps_nav_path_count >= 2048 { return ps_dock_diag_reason(6); }')
    return main, dock, search, nav
