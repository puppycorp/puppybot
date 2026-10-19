import "server.flex";
import "../host/serial.flex";
import "../platform/fake.flex";

fn pr_usage() {
    return pl_print(1, "Usage: puppybot-runtime [--fake | --servo-device PATH] [--config PATH]\n       [--bind IPv4:PORT] [--baud RATE] [--ticks N] [--headless]\n\n--fake uses a byte-level fake bus, without RobotDreams physics.\n");
}
fn pr_options(argc, argv, options) {
    pb_zero(options, 128); let config = pl_environment(argc, argv, "PUPPYBOT_RUNTIME_CONFIG");
    if !config || !load8(config) { config = "./puppybot.json"; } pb_vset(options, 0, config);
    let bind = pl_environment(argc, argv, "PUPPYBOT_RUNTIME_ADDR"); if bind && !load8(bind) { bind = 0; } pb_vset(options, 1, bind);
    let device = pl_environment(argc, argv, "PUPPYBOT_STSERVO_PORT"); if device && !load8(device) { device = 0; } pb_vset(options, 2, device);
    pb_vset(options, 4, 1000000); let baud = pl_environment(argc, argv, "PUPPYBOT_STSERVO_BAUD");
    if baud && load8(baud) { let value = pl_integer(baud, pl_size(baud)); if pl_bad_number || value < 1 || value > 4000000 { return -1; } pb_vset(options, 4, value); }
    let i = 1;
    while i < argc {
        let arg = load64(argv + i * 8);
        if pl_equal(arg, "--help") || pl_equal(arg, "-h") { return 1; }
        if pl_equal(arg, "--fake") { pb_vset(options, 3, 1); }
        else if pl_equal(arg, "--headless") {}
        else if pl_equal(arg, "--config") || pl_equal(arg, "--bind") || pl_equal(arg, "--servo-device") || pl_equal(arg, "--baud") || pl_equal(arg, "--ticks") {
            if i + 1 >= argc { return -1; } i = i + 1; let value = load64(argv + i * 8); if !load8(value) { return -1; }
            if pl_equal(arg, "--config") { pb_vset(options, 0, value); }
            if pl_equal(arg, "--bind") { pb_vset(options, 1, value); }
            if pl_equal(arg, "--servo-device") { pb_vset(options, 2, value); }
            if pl_equal(arg, "--baud") || pl_equal(arg, "--ticks") {
                let number = pl_integer(value, pl_size(value)); if pl_bad_number || number < 1 { return -1; }
                if pl_equal(arg, "--baud") { if number > 4000000 { return -1; } pb_vset(options, 4, number); }
                else { if number > 1000000000 { return -1; } pb_vset(options, 5, number); }
            }
        } else { return -1; }
        i = i + 1;
    }
    if pb_vget(options, 3) && pb_vget(options, 2) { return -1; }
    if !pb_vget(options, 1) { if pb_vget(options, 3) { pb_vset(options, 1, "127.0.0.1:8080"); } else { pb_vset(options, 1, "0.0.0.0:8080"); } }
    return 0;
}
fn pr_bind_address(text, address) {
    let size = pl_size(text); let colon = ph_find(text, size, ":", 1); if colon < 1 { return 0; }
    let port = pl_integer(text + colon + 1, size - colon - 1);
    if pl_bad_number || port < 0 || port > 65535 { return 0; } return pl_sockaddr(address, text, colon, port);
}
fn pr_fake_setup(bus, config) {
    pb_fake_init(bus); let i = 0;
    while i < 4 { let j = pb_config_joint(config, i); pb_fake_servo(bus, pb_vget(j, 0), pb_canonical(pb_vget(j, 3))); i = i + 1; }
    let id = pb_vget(config + 40, 2);
    if id && pb_servo_id(id) && !pb_vget(bus + id * 48, 0) { pb_fake_servo(bus, id, pb_servo_angle(pb_vget(config + 40, 3))); }
    return 0;
}
fn pr_fake_advance(bus) {
    let id = 1;
    while id <= 253 {
        let servo = bus + id * 48;
        if pb_vget(servo, 0) && pb_vget(servo, 1) {
            let remaining = bus + 14336 + id * 8;
            let distance = load64(remaining) + pb_vget(servo, 3) * 20;
            let tick = distance / 1000; store64(remaining, distance % 1000);
            pb_vset(servo, 2, pb_canonical(pb_vget(servo, 2) + tick));
        }
        id = id + 1;
    }
    return 0;
}
fn pr_emergency(app, now) {
    pr_stop(app, now); let system = pb_vget(app, 1); let stage = pb_vget(system, 1); let index = pb_vget(system, 2); let pending = pb_vget(system, 6);
    let i = 0;
    while i < 4 {
        if !(stage == 4 && i == index && !pending) { pb_vset(system + 640 + i * 24, 1, 0); pb_vset(system + 640 + i * 24, 2, 1); } i = i + 1;
    }
    if stage == 4 && pending { let id = pb_vget(system + 640 + index * 24, 0); pb_servo_wheel(system + 128, 256, id, 0, 0, system + 512); }
    return 0;
}
fn pr_poll_fds(buffer, signal, serial) {
    let count = 0;
    if pn_listener >= 0 { store64(buffer, (pn_listener & 0xffffffff) | (1 << 32)); count = count + 1; }
    if signal >= 0 { store64(buffer + count * 8, (signal & 0xffffffff) | (1 << 32)); count = count + 1; }
    if serial && load64(serial) >= 0 {
        let events = 1; if pb_vget(serial, 1) { events = events | 4; }
        store64(buffer + count * 8, (load64(serial) & 0xffffffff) | (events << 32)); count = count + 1;
    }
    let i = 0;
    while i < 32 {
        let c = pn_clients + i * 65536;
        if load64(c) >= 0 {
            let events = 0; let mode = pb_vget(c, 1);
            if (mode == 0 || mode == 2) && !pb_vget(c, 13) && !pb_vget(c, 15) { events = 1; }
            if mode == 4 { events = 1; }
            if pb_vget(c, 4) < pb_vget(c, 3) { events = events | 4; }
            if events { store64(buffer + count * 8, (load64(c) & 0xffffffff) | (events << 32)); count = count + 1; }
        }
        i = i + 1;
    }
    return count;
}
fn pr_reconnect(app, now) {
    let serial = pb_vget(app, 4); if load64(serial) >= 0 { pb_vset(app, 33, now + 1000); return 0; }
    if now < pb_vget(app, 33) { return 0; } pb_vset(app, 33, now + 1000);
    let fd = ps_open(pb_vget(app, 31), pb_vget(app, 32)); if fd < 0 { return 0; }
    pr_stop(app, now); let robot = load64(app); let system = pb_vget(app, 1);
    let i = 0; while i < 4 { pb_arm_feedback_error(robot, i); i = i + 1; }
    store64(robot + 4256, -1); pb_system_init(system, robot); ps_init(serial, fd);
    pr_last(app, "serial reconnected; motion stopped"); return 1;
}
fn pr_loop(app, tick_limit) {
    let robot = load64(app); let system = pb_vget(app, 1); let serial = pb_vget(app, 4); let fake = pb_vget(app, 8); let bus = pb_vget(app, 3);
    let signal = pl_signals(); if signal < 0 { return 1; }
    let poll = alloc(512); let signal_bytes = alloc(128); let trace = alloc(1024);
    let next_tick = 0; let ticks = 0; let stopping = 0; let stop_deadline = 0; let stop_cycle = 0;
    while 1 {
        let now = pl_now() - pb_vget(app, 6); if now < 0 { return 2; }
        if !stopping && (syscall(0, signal, signal_bytes, 128, 0, 0, 0) > 0 || (tick_limit && ticks >= tick_limit)) {
            stopping = 1; stop_deadline = now + 1000; pr_emergency(app, now);
            if pn_listener >= 0 { syscall(3, pn_listener, 0, 0, 0, 0, 0); pn_listener = -1; }
        }
        if !fake && !stopping { pr_reconnect(app, now); }
        let active = pb_system_active(system);
        if !fake && active { if ps_pump(serial, system, now) < 0 { pr_stop(app, now); } }
        if active && !pb_system_active(system) { ticks = ticks + 1; if !stopping { pnet_telemetry(app, now); } }
        if stopping && ((!pb_system_active(system) && stop_cycle) || now >= stop_deadline) { return 0; }
        pnet_io(now);
        if !pb_system_active(system) {
            if !stopping { pnet_dispatch(app, now); if fake || load64(serial) >= 0 { pr_refresh(app, now); } }
            if stopping || now >= next_tick {
                next_tick = now + 20; if stopping { stop_cycle = 1; }
                if fake {
                    pr_fake_advance(bus); let n = pb_fake_cycle(system, bus, now, trace, 1024); if n < 0 { return 3; }
                    ticks = ticks + 1; if !stopping { pnet_telemetry(app, now); }
                } else if load64(serial) >= 0 { pb_system_begin(system, now); if ps_pump(serial, system, now) < 0 { pr_stop(app, now); } if !pb_system_active(system) { ticks = ticks + 1; if !stopping { pnet_telemetry(app, now); } } }
                else { if stopping { return 0; } }
            }
        }
        let count = pr_poll_fds(poll, signal, serial); let wait = 5;
        if !pb_system_active(system) { wait = pb_clamp(next_tick - now, 0, 5); }
        if stopping { wait = 1; } syscall(7, poll, count, wait, 0, 0, 0);
    }
    return 0;
}
fn main(argc, argv) {
    if !pl_init() { return 1; }
    let options = alloc(128); let parsed = pr_options(argc, argv, options);
    if parsed == 1 { pr_usage(); return 0; } if parsed < 0 { pr_usage(); return 2; }
    let address = alloc(16); if !pr_bind_address(pb_vget(options, 1), address) { pl_print(2, "Invalid IPv4 bind address.\n"); return 2; }
    let config = alloc(448); let input = alloc(65537); let robot = alloc(8192); let system = alloc(2048); let app = alloc(2048);
    let serial = alloc(512); let bus = alloc(16384); let saved = alloc(65536);
    if config <= 0 || input <= 0 || robot <= 0 || system <= 0 || app <= 0 || serial <= 0 || bus <= 0 || saved <= 0 { return 1; }
    let loaded = pc_load(config, pb_vget(options, 0), input);
    if loaded < 0 { pl_print(2, "Invalid configuration: "); if pj_message { pl_print(2, pj_message); } pl_print(2, "\n"); return 2; }
    let fake = pb_vget(options, 3);
    if fake && !loaded { pb_vset(config + 40, 2, 5); }
    if pl_signals() < 0 { return 1; }
    let fd = -1;
    if !fake {
        let path = pb_vget(options, 2); if !path { pl_print(2, "Select a serial bus with --servo-device PATH, or use --fake.\n"); return 2; }
        fd = ps_open(path, pb_vget(options, 4)); if fd < 0 { pl_print(2, "Cannot open/configure the selected STServo device.\n"); return 1; }
    }
    let started = pl_now(); if pb_robot_configure(robot, config, 0) { if fd >= 0 { syscall(3, fd, 0, 0, 0, 0, 0); } return 2; }
    pb_system_init(system, robot); ps_init(serial, fd); pr_init(app, robot, system, config, pb_vget(options, 0), fake, started);
    pb_vset(app, 3, bus); pb_vset(app, 4, serial); pb_vset(app, 30, saved); if fake { pr_fake_setup(bus, config); }
    pb_vset(app, 31, pb_vget(options, 2)); pb_vset(app, 32, pb_vget(options, 4));
    if pnet_init(address) < 0 { pl_print(2, "Cannot bind the runtime listener.\n"); if fd >= 0 { syscall(3, fd, 0, 0, 0, 0, 0); } return 1; }
    let b = pl_scratch + 512; pl_builder(b, input, 65537); pl_text(b, "Puppybot runtime listening on port "); pl_uint(b, pn_port);
    if fake { pl_text(b, " (fake)\n"); } else { pl_text(b, " (hardware)\n"); } pl_print(1, input);
    let result = pr_loop(app, pb_vget(options, 5));
    if load64(serial) >= 0 { syscall(3, load64(serial), 0, 0, 0, 0, 0); }
    if pn_listener >= 0 { syscall(3, pn_listener, 0, 0, 0, 0, 0); }
    let i = 0; while i < 32 { pnet_close(pn_clients + i * 65536); i = i + 1; } return result;
}
