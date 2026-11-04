fn main(argc, argv) {
    if !pl_init() { return 1; }
    ps_dock_diag_dir = "@@DIAG@@"; ps_dock_diag_searches = 1;
    ps_dock_diag_plan_reason = 3; ps_dc_last_reason = 2; ps_total = 100;
    let goal = alloc(24); pb_zero(goal, 24);
    if !ps_dock_diag_candidate(0, goal, 0) { return 1; }
    ps_dock_diag_searches = 2; ps_total = 200;
    if !ps_dock_diag_candidate(0, goal, 0) || ps_dock_diag_write_errors || ps_dock_diag_plan_count != 2 { return 2; }
    pl_print(1, "separate diagnostic sweeps written\n"); return 0;
}
