fn main(argc, argv) {
    if argc != 5 { return 2; }
    pl_init(); h_environment(argc, argv);
    ps_robot = alloc(8192); ps_plant = alloc(512); let bus = alloc(256); store64(ps_plant + 8, bus);
    ps_nav_map = alloc(40000); ps_discovery_observed = alloc(40000); ps_discovery_detail = alloc(1000000); ps_discovery_goals = alloc(8 * 24);
    ps_total = 370; ps_discovery_frame_id = 369; ps_discovery_map_frame = -1;
    ps_discovery_directory = load64(argv + 24); ps_discovery_barrier_enabled = 1;
    let args = h_args("/usr/bin/python3", load64(argv + 8), load64(argv + 32), load64(argv + 16), ps_discovery_directory, 0);
    ps_discovery_job = h_spawn(args, "", 0); ps_discovery_started = pl_now();
    if !ps_discovery_barrier_wait() { pl_print(2, "worker barrier failed\n"); return 1; }
    if !ps_discovery_result() { pl_print(2, "real worker output rejected\n"); return 1; }
    if ps_discovery_map_frame != 369 || ps_total != 370 { pl_print(2, "map frame or tick mismatch\n"); return 1; }
    pl_print(1, "{\"mapFrameId\":"); pl_print(1, h_int(ps_discovery_map_frame));
    pl_print(1, ",\"mapApplyTick\":"); pl_print(1, h_int(ps_total));
    pl_print(1, ",\"workerCompleteTick\":"); pl_print(1, h_int(ps_discovery_barrier_last_tick));
    pl_print(1, ",\"workerWallMs\":"); pl_print(1, h_int(ps_discovery_barrier_last_wall_ms));
    pl_print(1, ",\"freeCells\":"); pl_print(1, h_int(ps_discovery_free));
    pl_print(1, ",\"safeCells\":"); pl_print(1, h_int(ps_discovery_safe));
    pl_print(1, "}\n"); return 0;
}
