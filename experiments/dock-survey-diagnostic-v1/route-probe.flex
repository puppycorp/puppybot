// Planner's entry branches execute with fixture map and clearance primitives.
fn sr_require(ok, message) { if !ok { pl_print(2, message); pl_print(2, "\n"); syscall(231, 1, 0, 0, 0, 0, 0); } return 0; }
fn main(argc, argv) {
    if !pl_init() { return 2; }
    ps_dock_diag_dir = "fixture"; ps_nav_goal = alloc(24); ps_nav_nodes = alloc(80); ps_nav_capacity = 1; ps_nav_map = alloc(16);
    sd_heading = 1; sd_cell = -1;
    sr_require(!ps_nav_plan(0, 0, 0) && ps_dock_diag_plan_reason == 1, "outside goal category");
    sd_cell = 0; store8(ps_nav_map, 1);
    sr_require(!ps_nav_plan(0, 0, 0) && ps_dock_diag_plan_reason == 2, "blocked cell category");
    sd_heading = 0; sd_clear = 0;
    sr_require(!ps_nav_plan(0, 0, 0) && ps_dock_diag_plan_reason == 3, "configuration category");
    sd_clear = 1;
    sr_require(!ps_nav_plan(0, 0, 0) && ps_dock_diag_plan_reason == 4, "start category");
    ps_dock_diag_dir = 0; ps_dock_diag_plan_reason = 77; sd_heading = 1; sd_cell = -1;
    sr_require(!ps_nav_plan(0, 0, 0) && ps_dock_diag_plan_reason == 77, "disabled planner hook changed diagnostic state");
    return 0;
}
