fn main(argc, argv) {
    pl_init(); h_environment(argc, argv);
    ps_robot = alloc(8192); ps_plant = alloc(512); let bus = alloc(256); store64(ps_plant + 8, bus);
    ps_total = 1622; ps_discovery_frame_id = 1621; ps_discovery_map_frame = 999;
    ps_discovery_phase = 3; ps_discovery_enabled = 1; ps_discovery_barrier_enabled = 1;
    let args = h_args("/usr/bin/printf", "{broken", 0, 0, 0, 0);
    ps_discovery_job = h_spawn(args, "", 0); ps_discovery_started = pl_now();
    let result = ps_discovery_update();
    if result || ps_discovery_phase != 7 || ps_discovery_map_frame != 999 || ps_discovery_job ||
       ps_discovery_barrier_waits != 1 || ps_discovery_barrier_last_tick != 1622 ||
       !pl_equal(ps_discovery_reason, "stereo worker failed; no blind motion") {
        pl_print(2, "Malformed worker output was not rejected safely.\n"); return 1;
    }
    pl_print(1, "Malformed worker output rejected without applying map.\n"); return 0;
}
