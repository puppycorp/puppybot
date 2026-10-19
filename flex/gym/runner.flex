import "ipc.flex";
import "plant.flex";
import "../host/config.flex";

// One retained run arena; only the firmware process owns controller state.
global gr_context = 0;
global gr_error = 0;

fn gr_fail(message) { gr_error = message; return 0; }
fn gr_path(out, directory, leaf) {
    let b = pl_scratch + 512; pl_builder(b, out, 4096); pl_text(b, directory); pl_char(b, 47); pl_text(b, leaf); return !load64(b + 24);
}
fn gr_hex(builder, bytes, size) {
    let alphabet = "0123456789abcdef"; pl_char(builder, 34); let i = 0;
    while i < size { let value = load8(bytes + i); pl_char(builder, load8(alphabet + (value >> 4))); pl_char(builder, load8(alphabet + (value & 15))); i = i + 1; }
    return pl_char(builder, 34);
}
fn gr_int_array(b, values, size) {
    pl_char(b, 91); let i = 0; while i < size { if i { pl_char(b, 44); } pl_int(b, pb_vget(values, i)); i = i + 1; } return pl_char(b, 93);
}
fn gr_write_json(context, leaf) {
    let path = context + 4096; if !gr_path(path, load64(context), leaf) { return gr_fail("artifact path exceeds limit"); }
    let b = context + 256; if load64(b + 24) || pl_atomic_file(path, context + 8192, load64(b + 8)) { return gr_fail("cannot persist run artifact"); } return 1;
}
fn gr_plant_json(context, b) {
    let plant = pb_vget(context, 2); let bus = pb_vget(context, 3); pl_char(b, 91); let i = 0;
    while i < 4 {
        let j = plant + 128 + i * 64; let servo = bus + pb_vget(j, 3) * 48; if i { pl_char(b, 44); }
        pl_text(b, "{\"servoId\":"); pl_int(b, pb_vget(j, 3)); pl_text(b, ",\"tick\":"); pl_int(b, pb_vget(j, 2));
        pl_text(b, ",\"velocity\":"); pl_int(b, pb_vget(j, 1)); pl_text(b, ",\"command\":"); pl_int(b, pb_vget(servo, 3));
        pl_text(b, ",\"mode\":"); pl_int(b, pb_vget(servo, 1)); pl_char(b, 125); i = i + 1;
    }
    return pl_char(b, 93);
}
fn gr_status(context, state, reason, passed) {
    let b = context + 256; pl_builder(b, context + 8192, 8192);
    pl_text(b, "{\"schema\":\"puppybotgym.run.v1\",\"case\":"); pj_text(b, pb_vget(context, 7));
    pl_text(b, ",\"seed\":"); pl_uint(b, pb_vget(context, 8)); pl_text(b, ",\"status\":"); pj_text(b, state);
    pl_text(b, ",\"reason\":"); pj_text(b, reason); pl_text(b, ",\"passed\":"); pj_bool_text(b, passed);
    pl_text(b, ",\"backend\":\"servo-plant-v1\",\"firmwareTarget\":\"native-linux\",\"articulatedPhysics\":false,\"stepMs\":20,\"step\":"); pl_uint(b, pb_vget(context, 9));
    pl_text(b, ",\"timeMs\":"); pl_uint(b, pb_vget(context, 10)); pl_text(b, ",\"serialPackets\":"); pl_uint(b, pb_vget(context, 11));
    pl_text(b, ",\"modeAcknowledgements\":"); pl_uint(b, pb_vget(context, 12)); pl_text(b, ",\"fault\":"); pj_text(b, context + 512);
    pl_text(b, ",\"targets\":"); gr_int_array(b, context + 384, 4); pl_text(b, ",\"plant\":"); gr_plant_json(context, b);
    pl_text(b, "}\n"); return gr_write_json(context, "progress.json");
}
fn gr_copy_firmware(source, target) {
    let input = syscall(2, source, 0x80000, 0, 0, 0, 0); if input < 0 { return 0; }
    let output = syscall(2, target, 0x800c1, 448, 0, 0, 0); if output < 0 { syscall(3, input, 0, 0, 0, 0, 0); return 0; }
    let buffer = alloc(65536); let size = 0; let ok = 1; let active = 1;
    while active {
        let n = syscall(0, input, buffer, 65536, 0, 0, 0);
        if n > 0 { size = size + n; if size > 16777216 || pl_write(output, buffer, n) { ok = 0; active = 0; } }
        else if n != -4 { active = 0; if n < 0 { ok = 0; } }
    }
    if syscall(74, output, 0, 0, 0, 0, 0) { ok = 0; }
    syscall(3, input, 0, 0, 0, 0, 0); syscall(3, output, 0, 0, 0, 0, 0); return ok && size > 0;
}
fn gr_log_packet(context, request, n, reply, size) {
    let b = context + 288; pl_builder(b, context + 16384, 4096);
    pl_text(b, "{\"timeMs\":"); pl_uint(b, pb_vget(context, 10)); pl_text(b, ",\"tx\":"); gr_hex(b, request, n); pl_text(b, ",\"rx\":");
    if size < 0 { pl_text(b, "null"); } else { gr_hex(b, reply, size); } pl_text(b, "}\n");
    if load64(b + 24) || pl_write(pb_vget(context, 5), context + 16384, load64(b + 8)) { return gr_fail("cannot write serial journal"); } return 1;
}
fn gr_exchange(context, expected) {
    let fd = pb_vget(context, 1); let count = 0;
    while count < 21 {
        if gx_receive(fd, 2000) != 1 { return gr_fail("firmware transport closed or timed out"); }
        if gx_kind == expected { return 1; }
        if gx_kind != 102 || gx_size > 256 { return gr_fail("unexpected firmware message"); }
        let reply = pb_vget(context, 3) + 14000; let n = gx_size;
        let size = pb_fake_transaction(pb_vget(context, 3), gx_rx + 24, n, reply);
        if !gr_log_packet(context, gx_rx + 24, n, reply, size) { return 0; }
        pb_vset(context, 11, pb_vget(context, 11) + 1);
        if n == 8 && load8(gx_rx + 28) == 3 && load8(gx_rx + 29) == 33 && size > 0 { pb_vset(context, 12, pb_vget(context, 12) + 1); }
        if size <= 0 { if !gx_send(fd, 4, reply, 0) { return 0; } } else { if !gx_send(fd, 3, reply, size) { return 0; } }
        count = count + 1;
    }
    return gr_fail("firmware cycle exceeded exchange bound");
}
fn gr_wire(context, command, body, size) {
    let data = context + 1024; store64(data, pb_vget(context, 10)); store8(data + 8, 1); store8(data + 9, command); pb_put16(data + 10, size); pb_copy(data + 12, body, size);
    let b = context + 288; pl_builder(b, context + 16384, 4096); pl_text(b, "{\"timeMs\":"); pl_uint(b, pb_vget(context, 10));
    pl_text(b, ",\"frame\":"); gr_hex(b, data + 8, size + 4); pl_text(b, "}\n");
    if pl_write(pb_vget(context, 6), context + 16384, load64(b + 8)) { return gr_fail("cannot write command journal"); }
    return gx_send(pb_vget(context, 1), 5, data, size + 12) && gr_exchange(context, 104);
}
fn gr_observation(context) {
    if gx_size < 4 || pb_u16(gx_rx + 24) != 1 || load8(gx_rx + 26) != 7 || load8(gx_rx + 27) != 4 { return gr_fail("invalid firmware telemetry"); }
    let at = 28; let i = 0;
    while i < 4 {
        if at + 25 > 24 + gx_size { return gr_fail("truncated firmware telemetry"); }
        let n = load8(gx_rx + at + 24); if n > 63 || at + 25 + n > 24 + gx_size { return gr_fail("invalid firmware fault"); }
        if !i { pb_copy(context + 512, gx_rx + at + 25, n); store8(context + 512 + n, 0); }
        at = at + 25 + n; i = i + 1;
    }
    let b = context + 288; pl_builder(b, context + 16384, 4096);
    pl_text(b, "{\"step\":"); pl_uint(b, pb_vget(context, 9)); pl_text(b, ",\"timeMs\":"); pl_uint(b, pb_vget(context, 10));
    pl_text(b, ",\"plant\":"); gr_plant_json(context, b); pl_text(b, ",\"telemetry\":"); gr_hex(b, gx_rx + 24, gx_size); pl_text(b, "}\n");
    if load64(b + 24) || pl_write(pb_vget(context, 4), context + 16384, load64(b + 8)) { return gr_fail("cannot write observation journal"); } return 1;
}
fn gr_prepare(options) {
    let context = alloc(24576); gr_context = context; let directory = pb_vget(options, 2); store64(context, directory);
    pb_vset(context, 7, load64(options)); pb_vset(context, 8, pb_vget(options, 1)); let path = context + 4096;
    if syscall(83, directory, 448, 0, 0, 0, 0) { return gr_fail("run directory must be new and its parent must exist"); }
    let config = alloc(448); pb_config_default(config); pb_zero(config + 8, 32); pb_copy(config + 8, "PB-GYM-0001", 11); pb_vset(config + 40, 2, 5);
    let bus = alloc(16384); let plant = alloc(2048); let stalled = pl_equal(load64(options), "joint-stall");
    gs_init(plant, config, bus, pb_vget(options, 1), stalled - 1); pb_vset(context, 2, plant); pb_vset(context, 3, bus);
    gs_targets(context + 384, config, pb_vget(options, 1), stalled);
    let b = context + 256; pl_builder(b, context + 8192, 8192); pc_emit(b, config); pl_char(b, 10); if !gr_write_json(context, "config.json") { return 0; }
    gr_path(path, directory, "firmware.elf"); if !gr_copy_firmware(pb_vget(options, 3), path) { return gr_fail("cannot snapshot native firmware executable"); }
    gr_path(path, directory, "gym.elf"); if !gr_copy_firmware("/proc/self/exe", path) { return gr_fail("cannot snapshot Gym executable"); }
    pl_builder(b, context + 8192, 8192);
    pl_text(b, "{\"schema\":\"puppybotgym.manifest.v1\",\"case\":"); pj_text(b, load64(options));
    pl_text(b, ",\"caseVersion\":1,\"policy\":\"scripted-joint-targets-v1\",\"seed\":"); pl_uint(b, pb_vget(options, 1));
    pl_text(b, ",\"stepLimit\":"); pl_uint(b, pb_vget(options, 4)); pl_text(b, ",\"stepMs\":20,\"warmupSteps\":64,\"settledSteps\":25,\"toleranceTicks\":8,\"accelerationTicksPerSecondSquared\":2000,\"backend\":\"servo-plant-v1\",\"articulatedPhysics\":false,\"firmware\":\"firmware.elf\",\"gym\":\"gym.elf\",\"config\":\"config.json\",\"targets\":");
    gr_int_array(b, context + 384, 4); pl_text(b, "}\n"); if !gr_write_json(context, "manifest.json") { return 0; }
    let names = alloc(24); store64(names, "observations.jsonl"); store64(names + 8, "serial.jsonl"); store64(names + 16, "commands.jsonl"); let i = 0;
    while i < 3 {
        gr_path(path, directory, pb_vget(names, i)); let fd = syscall(2, path, 0x800c1, 384, 0, 0, 0);
        if fd < 0 { return gr_fail("cannot create run journals"); } pb_vset(context, 4 + i, fd); i = i + 1;
    }
    return gr_status(context, "starting", "initializing native firmware", 0);
}
fn gr_start(context) {
    let executable = context + 2048; gr_path(executable, load64(context), "firmware.elf"); let path = context + 4096; gr_path(path, load64(context), "firmware.log");
    let args = alloc(32); store64(args, executable); store64(args + 8, "--gym-fd"); store64(args + 16, "3");
    if !gx_spawn(executable, args, path, context + 128) { return gr_fail("cannot start native firmware process"); }
    pb_vset(context, 1, load64(context + 136)); let config = load64(pb_vget(context, 2));
    if !gx_send(pb_vget(context, 1), 1, config, 448) || !gr_exchange(context, 101) || gx_size != 8 { return gr_fail("native firmware failed to boot"); }
    let b = context + 256; pl_builder(b, context + 8192, 8192);
    pl_text(b, "{\"schema\":\"puppybotgym.endpoint.v1\",\"firmwarePid\":"); pl_int(b, load64(context + 128));
    pl_text(b, ",\"url\":\"ws://127.0.0.1:"); pl_uint(b, load64(gx_rx + 24)); pl_text(b, "/ws\",\"backend\":\"servo-plant-v1\"}\n");
    if !gr_write_json(context, "endpoint.json") { return 0; }
    pl_print(1, context + 8192); return 1;
}
fn gr_control(context, paused) {
    let path = context + 4096; gr_path(path, load64(context), "control"); let data = context + 1792;
    let n = pl_read_file(path, data, 32);
    if n == -2 { return paused; } if n < 0 { return -2; }
    // Controls are durable desired state; repeated reads are idempotent.
    if pl_equal(data, "stop") { return -1; } if pl_equal(data, "pause") { return 1; } if pl_equal(data, "resume") { return 0; } return -2;
}
fn gr_run(options) {
    gr_error = 0; if !gr_prepare(options) { return 2; } let context = gr_context; let ok = gr_start(context);
    let outcome = "error"; let reason = "native firmware failed to start"; let passed = 0; let stable = 0; let paused = pb_vget(options, 6); let tick = 0;
    let stalled = pl_equal(load64(options), "joint-stall"); let active = ok; let signal = pl_signals(); let signal_data = alloc(128); let body = context + 1536;
    if paused && ok { gr_status(context, "paused", "simulation time is frozen", 0); }
    while active && tick < pb_vget(options, 4) {
        let control = gr_control(context, paused);
        if control < 0 || syscall(0, signal, signal_data, 128, 0, 0, 0) > 0 {
            outcome = "cancelled"; reason = "rollout stopped"; active = 0; if control == -2 { outcome = "error"; reason = "invalid control file"; }
        } else if control {
            if !paused { gr_status(context, "paused", "simulation time is frozen", 0); } paused = 1; syscall(7, 0, 0, 10, 0, 0, 0);
        } else {
            if paused { gr_status(context, "running", "rollout resumed", 0); } paused = 0;
            // Let every joint publish feedback and the reference controller's
            // one-second wheel-mode retry window expire before issuing motion.
            if tick == 64 { pb_put16(body, 200); let i = 0; while i < 4 { pb_put32(body + 2 + i * 4, pb_vget(context + 384, i)); i = i + 1; } ok = gr_wire(context, 16, body, 18); }
            gs_step(pb_vget(context, 2)); store64(body, tick * 20); pb_vset(context, 9, tick); pb_vset(context, 10, tick * 20);
            if ok { ok = gx_send(pb_vget(context, 1), 2, body, 8) && gr_exchange(context, 103) && gr_observation(context); }
            if !ok { active = 0; reason = "firmware or artifact failure"; }
            else {
                if tick > 64 && !stalled && gs_reached(pb_vget(context, 2), context + 384) && gs_stopped(pb_vget(context, 2)) { stable = stable + 1; } else { stable = 0; }
                if (stalled && pl_equal(context + 512, "stall") && gs_stopped(pb_vget(context, 2))) || stable >= 25 {
                    passed = 1; outcome = "passed"; reason = "case acceptance criteria met"; active = 0;
                }
                if tick % 25 == 0 && !gr_status(context, "running", "rollout in progress", 0) { active = 0; ok = 0; }
            }
            tick = tick + 1; if pb_vget(options, 5) { syscall(7, 0, 0, 20, 0, 0, 0); }
        }
    }
    if active { outcome = "failed"; reason = "case step limit reached"; }
    if load64(context + 128) > 0 {
        if ok && gx_send(pb_vget(context, 1), 6, body, 0) { ok = gr_exchange(context, 105); } else { ok = 0; }
        let status = gx_finish(load64(context + 128), pb_vget(context, 1)); if status || !gs_stopped(pb_vget(context, 2)) { ok = 0; }
    }
    if !ok { passed = 0; outcome = "error"; reason = "firmware or artifact failure"; }
    let i = 0; while i < 3 { let fd = pb_vget(context, 4 + i); if syscall(74, fd, 0, 0, 0, 0, 0) { passed = 0; outcome = "error"; reason = "journal fsync failed"; } syscall(3, fd, 0, 0, 0, 0, 0); i = i + 1; }
    if !gr_status(context, outcome, reason, passed) || !gr_write_json(context, "result.json") { return 2; }
    pl_print(1, context + 8192); if passed { return 0; } if pl_equal(outcome, "cancelled") { return 130; } return 1;
}
