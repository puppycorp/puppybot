// Independent real-time servo simulator. The controller runs in another process.
import "bus.flex";
import "../host/config.flex";

fn pv_usage() {
    return pl_print(1, "Usage: puppybot-simulator [--config PATH] [--state PATH] [--jam 0..3]\n       [--temperature 0..255] [--ticks N]\n\nCreates a private virtual STServo serial port and prints the connection command.\nUses ./puppybot.json by default. Keep this process running while Puppybot connects.\nModels encoders/velocity and jams; no 3D physics or measured thermal model.\n");
}
fn pv_options(argc, argv, options) {
    pb_zero(options, 64); store64(options, "./puppybot.json"); pb_vset(options, 2, -1); pb_vset(options, 3, 25);
    let i = 1;
    while i < argc {
        let arg = load64(argv + i * 8);
        if pl_equal(arg, "--help") || pl_equal(arg, "-h") { return 1; }
        if i + 1 >= argc { return -1; } i = i + 1; let value = load64(argv + i * 8); if !load8(value) { return -1; }
        if pl_equal(arg, "--config") { pb_vset(options, 0, value); }
        else if pl_equal(arg, "--state") { pb_vset(options, 1, value); }
        else if pl_equal(arg, "--jam") || pl_equal(arg, "--temperature") || pl_equal(arg, "--ticks") {
            let number = pl_integer(value, pl_size(value)); if pl_bad_number { return -1; }
            if pl_equal(arg, "--jam") { if number < 0 || number > 3 { return -1; } pb_vset(options, 2, number); }
            if pl_equal(arg, "--temperature") { if number < 0 || number > 255 { return -1; } pb_vset(options, 3, number); }
            if pl_equal(arg, "--ticks") { if number < 1 || number > 1000000000 { return -1; } pb_vset(options, 4, number); }
        } else { return -1; } i = i + 1;
    } return 0;
}
fn pv_same_file(a, b) {
    let info = alloc(288);
    if syscall(4, a, info, 0, 0, 0, 0) || syscall(4, b, info + 144, 0, 0, 0, 0) { return 0; }
    return load64(info) == load64(info + 144) && load64(info + 8) == load64(info + 152);
}
fn pv_quote(b, path) {
    pl_char(b, 39); let i = 0;
    while load8(path + i) { let byte = load8(path + i); if byte == 39 { pl_text(b, "'\\''"); } else { pl_char(b, byte); } i = i + 1; }
    return pl_char(b, 39);
}
fn pv_announce(path, config, output) {
    let b = pl_scratch + 512; pl_builder(b, output, 16384);
    pl_text(b, "Puppybot simulator listening on "); pl_text(b, path); pl_char(b, 10);
    pl_text(b, "Servo-motion model only; no 3D physics. Temperatures are synthetic.\n\nIn another terminal:\n  flexscript run puppybot.flex --servo-device ");
    pv_quote(b, path); pl_text(b, " --config "); pv_quote(b, config); pl_char(b, 10);
    pl_text(b, "Then open http://127.0.0.1:8081/ and enable outputs.\n"); return pl_print(1, output);
}
fn pv_state(context, path, steps, now, b, output) {
    pl_builder(b, output, 16384); pl_text(b, "{\"schema\":\"puppybot.simulator.v1\",\"backend\":\"servo-plant-v1\",\"articulatedPhysics\":false,\"device\":"); pj_text(b, path);
    pl_text(b, ",\"timeMs\":"); pl_uint(b, now); pl_text(b, ",\"steps\":"); pl_uint(b, steps);
    pl_text(b, ",\"serialPackets\":"); pl_uint(b, pb_vget(context, 5)); pl_text(b, ",\"malformedBytes\":"); pl_uint(b, pb_vget(context, 6));
    pl_text(b, ",\"joints\":["); let i = 0;
    while i < 4 {
        let j = pb_vget(context, 2) + 128 + i * 64; let servo = pb_vget(context, 3) + pb_vget(j, 3) * 48;
        if i { pl_char(b, 44); } pl_text(b, "{\"index\":"); pl_uint(b, i); pl_text(b, ",\"servoId\":"); pl_uint(b, pb_vget(j, 3));
        pl_text(b, ",\"tick\":"); pl_uint(b, pb_vget(j, 2)); pl_text(b, ",\"velocity\":"); pl_int(b, pb_vget(j, 1));
        pl_text(b, ",\"command\":"); pl_int(b, pb_vget(servo, 3)); pl_text(b, ",\"mode\":"); pl_uint(b, pb_vget(servo, 1));
        pl_text(b, ",\"temperatureC\":"); pl_uint(b, pb_vget(context, 4)); pl_char(b, 125); i = i + 1;
    } return pl_text(b, "]}\n");
}
fn pv_loop(context, path, options, b, output) {
    let input = alloc(4096); let pending = alloc(16384); let reply = alloc(128); let poll = alloc(16); let signal_data = alloc(128);
    let signal = pl_signals(); if signal < 0 { return 1; }
    let start = pl_now(); let next = start + 20; let steps = 0; let next_state = start;
    while 1 {
        if syscall(0, signal, signal_data, 128, 0, 0, 0) > 0 { return 0; }
        let now = pl_now(); if now < start { return 1; }
        let catchup = 0;
        while now >= next && catchup < 5 { gs_step(pb_vget(context, 2)); steps = steps + 1; next = next + 20; catchup = catchup + 1; }
        if now >= next { next = now + 20; }
        if pv_bytes(context, input, pending, reply, now) < 0 { pl_print(2, "Simulator serial I/O failed.\n"); return 1; }
        let finished = pb_vget(options, 4) && steps >= pb_vget(options, 4);
        if pb_vget(options, 1) && (now >= next_state || finished) {
            next_state = now + 100; pv_state(context, path, steps, now - start, b, output);
            if load64(b + 24) || pl_atomic_file(pb_vget(options, 1), output, load64(b + 8)) { pl_print(2, "Cannot write simulator state.\n"); return 1; }
        }
        if finished { return 0; }
        let events = 1; if pb_vget(context, 8) > pb_vget(context, 9) { events = events | 4; }
        store64(poll, (load64(context) & 0xffffffff) | (events << 32)); store64(poll + 8, (signal & 0xffffffff) | (1 << 32));
        syscall(7, poll, 2, pb_clamp(next - now, 0, 5), 0, 0, 0);
    } return 0;
}
fn main(argc, argv) {
    if !pl_init() { return 1; }
    let options = alloc(64); let parsed = pv_options(argc, argv, options);
    if parsed == 1 { pv_usage(); return 0; } if parsed < 0 { pv_usage(); return 2; }
    let config = alloc(448); let output = alloc(16384); let b = alloc(32); let input = alloc(65537);
    let loaded = pc_load(config, load64(options), input);
    if loaded != 1 { pl_print(2, "Simulator requires an existing valid --config file (default ./puppybot.json).\n"); return 2; }
    if pb_vget(options, 1) && pv_same_file(load64(options), pb_vget(options, 1)) {
        pl_print(2, "Simulator --state must not overwrite the calibration file.\n"); return 2;
    }
    let context = alloc(512); pb_zero(context, 512); store64(context, -1); pb_vset(context, 1, -1);
    let plant = alloc(2048); let bus = alloc(16384); gs_init(plant, config, bus, 0, pb_vget(options, 2));
    pb_vset(context, 2, plant); pb_vset(context, 3, bus); pb_vset(context, 4, pb_vget(options, 3));
    let path = alloc(128); let fd = pv_pty(context, path);
    if fd < 0 { pl_builder(b, output, 16384); pl_text(b, "Cannot create the virtual serial port (error "); pl_int(b, fd); pl_text(b, ").\n"); pl_print(2, output); return 1; }
    pv_announce(path, load64(options), output);
    let result = pv_loop(context, path, options, b, output);
    syscall(3, pb_vget(context, 1), 0, 0, 0, 0, 0); syscall(3, fd, 0, 0, 0, 0, 0); return result;
}
