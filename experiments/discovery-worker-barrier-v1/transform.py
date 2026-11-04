#!/usr/bin/env python3
"""Isolated virtual-agent barrier for the asynchronous stereo worker."""


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('archived simulator differs from expected anchor')
    return source.replace(old, new, 1)


GLOBAL = '''global ps_discovery_barrier_enabled = 0;
global ps_discovery_barrier_waits = 0;
global ps_discovery_barrier_last_frame = -1;
global ps_discovery_barrier_last_tick = -1;
global ps_discovery_barrier_last_wall_ms = -1;
global ps_discovery_barrier_failures = 0;
'''


HELPER = '''// Simulation-only: pause simulated ticks while one asynchronous stereo job
// completes. Wall latency is recorded separately and checked against a
// cooperative deadline; it is not charged to simulated time. This is not a
// hardware or real-time watchdog: h_pump and h_stop may themselves block.
fn ps_discovery_barrier_wait() {
    let drive = pb_robot_drive(ps_robot);
    if !ps_discovery_job || load64(drive + 48) || load64(drive + 56) || !ps_camera_still() {
        ps_discovery_barrier_failures = ps_discovery_barrier_failures + 1;
        return ps_discovery_finish("worker barrier needs stationary simulated sensors and drive", 1);
    }
    let started = ps_discovery_started; let last = pl_now();
    if started < 0 || last < started {
        ps_discovery_barrier_failures = ps_discovery_barrier_failures + 1;
        return ps_discovery_finish("worker barrier clock failure", 1);
    }
    while 1 {
        let now = pl_now();
        if now < 0 || now < last || now - started >= 15000 {
            ps_discovery_barrier_failures = ps_discovery_barrier_failures + 1;
            return ps_discovery_finish("worker barrier timeout or clock failure", 1);
        }
        last = now; h_pump(ps_discovery_job, 10);
        now = pl_now();
        if now < 0 || now < last || now - started >= 15000 {
            ps_discovery_barrier_failures = ps_discovery_barrier_failures + 1;
            return ps_discovery_finish("worker barrier timeout or clock failure", 1);
        }
        last = now;
        if load64(ps_discovery_job + 8) != -999 && load64(ps_discovery_job + 40) < 0 && load64(ps_discovery_job + 48) < 0 {
            ps_discovery_barrier_waits = ps_discovery_barrier_waits + 1;
            ps_discovery_barrier_last_frame = ps_discovery_frame_id;
            ps_discovery_barrier_last_tick = ps_total;
            ps_discovery_barrier_last_wall_ms = now - started;
            return 1;
        }
    }
}
'''


def transform(discovery, main):
    discovery = once(discovery, 'global ps_discovery_job = 0;\n',
                     'global ps_discovery_job = 0;\n' + GLOBAL)
    discovery = once(discovery, 'fn ps_discovery_reset() {', HELPER + 'fn ps_discovery_reset() {')
    old = '''        h_pump(ps_discovery_job, 1);
        if load64(ps_discovery_job + 8) == -999 { if pl_now() - ps_discovery_started > 15000 { h_stop(ps_discovery_job); ps_discovery_job = 0; return ps_discovery_finish("mapping worker timed out", 1); } return 1; }
        if load64(ps_discovery_job + 40) >= 0 || load64(ps_discovery_job + 48) >= 0 { return 1; }
'''
    new = '''        if ps_discovery_barrier_enabled {
            if !ps_discovery_barrier_wait() { return 0; }
        } else {
            h_pump(ps_discovery_job, 1);
            if load64(ps_discovery_job + 8) == -999 { if pl_now() - ps_discovery_started > 15000 { h_stop(ps_discovery_job); ps_discovery_job = 0; return ps_discovery_finish("mapping worker timed out", 1); } return 1; }
            if load64(ps_discovery_job + 40) >= 0 || load64(ps_discovery_job + 48) >= 0 { return 1; }
        }
'''
    discovery = once(discovery, old, new)
    anchor = '    pl_text(b, ",\\\"mapFrameId\\\":"); pl_int(b, ps_discovery_map_frame);'
    insertion = '''    if ps_discovery_barrier_enabled {
        pl_text(b, ",\\\"workerBarrier\\\":{\\\"waits\\\":"); pl_int(b, ps_discovery_barrier_waits);
        pl_text(b, ",\\\"lastFrameId\\\":"); pl_int(b, ps_discovery_barrier_last_frame);
        pl_text(b, ",\\\"lastWorkerCompleteTick\\\":"); pl_int(b, ps_discovery_barrier_last_tick);
        pl_text(b, ",\\\"lastWallMs\\\":"); pl_int(b, ps_discovery_barrier_last_wall_ms);
        pl_text(b, ",\\\"failures\\\":"); pl_int(b, ps_discovery_barrier_failures); pl_char(b, 125);
    }
'''
    discovery = once(discovery, anchor, insertion + anchor)
    anchor = '    let high_survey = pl_environment(argc, argv, "PUPPYBOT_DOCK_HIGH_SURVEY");'
    main = once(main, anchor, '''    let worker_barrier = pl_environment(argc, argv, "PUPPYBOT_SIM_WORKER_BARRIER");
    if worker_barrier {
        if !pl_equal(worker_barrier, "0") && !pl_equal(worker_barrier, "1") { pl_print(2, "Invalid worker barrier option.\\n"); return 2; }
        ps_discovery_barrier_enabled = pl_equal(worker_barrier, "1");
    }
''' + anchor)
    anchor = '    if ps_external && (case_id || case_file || demo || pickup || ps_discovery_enabled || ps_stock_enabled || ps_gym_directory || ps_crumb_enabled)'
    main = once(main, anchor, '''    if ps_discovery_barrier_enabled && (ps_external || !ps_agent_physical || !ps_agent_fd || realtime) {
        pl_print(2, "Worker barrier is restricted to a non-realtime virtual physical-agent simulation.\\n"); return 2;
    }
''' + anchor)
    return discovery, main
