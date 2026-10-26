// Synchronous pixel/control Gym bridge. Physics and actuator guards still run;
// navigation, mapping workers and autonomous camera sweeps do not.
global ps_agent_fd = 0;
global ps_agent_task = 2;
global ps_agent_sequence = 0;
global ps_agent_blocked = 0;

fn ps_agent_read(data, size) {
    let offset = 0;
    while offset < size {
        let count = syscall(0, ps_agent_fd, data + offset, size - offset, 0, 0, 0);
        if count <= 0 { return 0; } offset = offset + count;
    } return 1;
}
fn ps_agent_begin() {
    ps_gripper_auto = 0; ps_gripper_command(0); ps_case_phase(26);
    ps_discovery_phase = 0; ps_agent_blocked = 0;
    ps_case_reason = "external visual policy controls steering and speed";
    return ps_camera_drive_target();
}
fn ps_agent_render(video, final) {
    if !video || !ps_video_due(ps_total, final) { return 1; }
    ps_frame(); let ok = ps_video_frame(ps_total, final); gui_gl_swap(load64(ps_device)); return ok;
}
fn ps_agent_observe() {
    if !ps_rgb_sample() { return 0; }
    ps_seek_observe();
    if ps_agent_task == 1 && ps_seek_found {
        ps_case_reason = "visual approach curriculum completed"; ps_case_passed = 1; ps_case_phase(12);
        pr_stop(ps_app, ps_time); ps_discovery_finish(ps_case_reason, 0);
    }
    let output = ps_output; ps_output = -1; let ok = ps_observation(); ps_output = output;
    if !ok { return 0; }
    let header = alloc(32); store64(header, load64(ps_builder + 8)); store64(header + 8, 640 * 480 * 3);
    store64(header + 16, ps_agent_sequence); store64(header + 24, ps_agent_blocked);
    ok = !pl_write(ps_agent_fd, header, 32) && !pl_write(ps_agent_fd, ps_json, load64(ps_builder + 8)) && !pl_write(ps_agent_fd, ps_brick_rgb, 640 * 480 * 3);
    syscall(11, header, 32, 0, 0, 0, 0); return ok;
}
fn ps_agent_loop(video, capture) {
    let request = alloc(64); let running = 1;
    while running && ps_agent_read(request, 64) {
        let command = load64(request); ps_agent_sequence = load64(request + 8);
        if command == 3 { running = 0; }
        else if command == 1 {
            let task = load64(request + 48); if task < 1 || task > 2 { return 1; } ps_agent_task = task;
            if !ps_case_load(ps_case_index) || !ps_reset() || !ps_case_start() { return 1; }
            let ticks = 0;
            while ticks < 2500 && (!ps_camera_still() || !ps_pickup_settled() || ps_gripper_gap != ps_gripper_goal) {
                if !ps_tick(0) { return 1; } ticks = ticks + 1;
            }
            if !ps_camera_still() || !ps_pickup_settled() { pl_print(2, "Agent driving-camera pose did not settle.\n"); return 1; }
            if !ps_agent_observe() || !ps_agent_render(video, 0) { return 1; }
        } else if command == 2 {
            let steering = load64(request + 16); let speed = load64(request + 24); let hold = load64(request + 32);
            if steering < -1000 || steering > 1000 || speed < -1000 || speed > 1000 || hold < 1 || hold > 20 || !ps_case_running() { return 1; }
            // Normalized actions map to steering and bounded wheel speed.
            // The dead zone permits an actual stop under a continuous policy.
            let throttle = speed * 60 / 1000; if pb_abs(speed) < 80 { throttle = 0; }
            ps_agent_blocked = 0; let tick = 0;
            while tick < hold {
                pb_drive_steer(pb_robot_drive(ps_robot), throttle, steering / 10, ps_time);
                if !ps_tick(0) { return 1; } if ps_blocked { ps_agent_blocked = 1; } tick = tick + 1;
            }
            if !ps_agent_observe() || !ps_agent_render(video, ps_case_passed) { return 1; }
        } else { return 1; }
    }
    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_discovery_phase = 6;
    if video && !ps_agent_render(video, 1) { return 1; }
    if capture { ps_frame(); if !ps_capture(capture) { return 1; } }
    syscall(11, request, 64, 0, 0, 0, 0); return 0;
}
