// Native firmware target: production controller/protocol, external virtual HAL.
// This is a native process, not an emulated ESP32 binary.
import "../runtime/server.flex";
import "../gym/ipc.flex";

fn pf_cycle(app, fd, now) {
    let system = pb_vget(app, 1); pb_system_begin(system, now); let exchanges = 0;
    while pb_system_active(system) {
        exchanges = exchanges + 1; if exchanges > 20 { return 0; }
        let n = pb_system_take_tx(system);
        if n < 1 || !gx_send(fd, 102, pb_system_packet(system), n) || gx_receive(fd, 2000) != 1 { return 0; }
        pb_system_written(system, now);
        if gx_kind == 4 && !gx_size { pb_system_error(system); }
        else if gx_kind == 3 && gx_size <= 128 {
            let i = 0; while i < gx_size { pb_system_receive(system, gx_rx + 24 + i, 1, now); i = i + 1; }
            if pb_system_active(system) && !pb_vget(system, 6) { pb_system_poll(system, now + 50); }
        } else { return 0; }
    }
    return 1;
}
fn pf_state(app, fd, scratch) { let n = pb_arm_state_frame(load64(app), scratch, 256); return n > 0 && gx_send(fd, 103, scratch, n); }
fn pf_main(fd) {
    if gx_receive(fd, 2000) != 1 || gx_kind != 1 || gx_size != 448 { return 2; }
    let config = alloc(448); pb_copy(config, gx_rx + 24, 448); let robot = alloc(8192); let system = alloc(2048); let app = alloc(2048);
    let scratch = alloc(4096); let serial = alloc(512); let saved = alloc(65536); let address = alloc(16);
    if pb_robot_configure(robot, config, 0) { return 2; } pb_system_init(system, robot);
    pr_init(app, robot, system, config, "", 1, pl_now()); pb_vset(app, 4, serial); pb_vset(app, 30, saved);
    pb_vset(app, 36, 1);
    // The target exposes the same robot API independently of Gym's management UI.
    pl_sockaddr(address, "127.0.0.1", 9, 0); if pnet_init(address) < 0 { return 3; }
    store64(scratch, pn_port); if !gx_send(fd, 101, scratch, 8) { return 3; }
    let now = 0; let alive = 1;
    while alive {
        let wall = pl_now(); pnet_io(wall); pnet_dispatch_at(app, wall, now); pnet_telemetry(app, wall);
        let n = gx_receive(fd, 0); if n < 0 { return 4; }
        if n == 1 {
            if gx_kind == 2 && gx_size == 8 {
                let next = load64(gx_rx + 24); if next < now || next > now + 1000 { return 2; } now = next;
                if !pf_cycle(app, fd, now) || !pf_state(app, fd, scratch) { return 4; } pnet_telemetry(app, wall);
            } else if gx_kind == 5 && gx_size >= 12 && gx_size <= 2060 {
                if load64(gx_rx + 24) != now { return 2; }
                let size = pr_wire(app, gx_rx + 32, gx_size - 8, scratch, now);
                if size < 0 || !gx_send(fd, 104, scratch, size) { return 4; }
            } else if gx_kind == 6 && !gx_size {
                pr_stop(app, now);
                if !pf_cycle(app, fd, now) || !gx_send(fd, 105, scratch, 0) { return 4; } alive = 0;
            } else { return 2; }
        } else { syscall(7, 0, 0, 1, 0, 0, 0); }
    }
    let i = 0; while i < 32 { pnet_close(pn_clients + i * 65536); i = i + 1; }
    syscall(3, pn_listener, 0, 0, 0, 0, 0); return 0;
}
fn main(argc, argv) {
    if !pl_init() || !gx_init(argc, argv) { return 1; }
    if argc != 3 || !pl_equal(load64(argv + 8), "--gym-fd") || !pl_equal(load64(argv + 16), "3") { pl_print(2, "Launch this native firmware target through puppybotgym.\n"); return 2; }
    return pf_main(3);
}
