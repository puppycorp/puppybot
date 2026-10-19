import "client.flex";

global pcl_argc = 0;
global pcl_argv = 0;
global pcl_marks = 0;
global pcl_error = 0;
global pcl_message = 0;

fn pcl_fail(message) { pcl_error = 1; pcl_message = message; return 0; }
fn pcl_option(name, fallback) {
    let found = 0; let i = 1;
    while i < pcl_argc {
        let arg = load64(pcl_argv + i * 8);
        if !load64(pcl_marks + i * 8) && pl_equal(arg, name) {
            if found || i + 1 >= pcl_argc || load64(pcl_marks + (i + 1) * 8) { return pcl_fail("duplicate option or missing option value"); }
            found = load64(pcl_argv + (i + 1) * 8);
            if pl_starts(found, "--") { return pcl_fail("missing option value"); }
            store64(pcl_marks + i * 8, 1); store64(pcl_marks + (i + 1) * 8, 1); i = i + 1;
        }
        i = i + 1;
    }
    if found { return found; } return fallback;
}
fn pcl_boolean(name) {
    let found = 0; let i = 1;
    while i < pcl_argc {
        if !load64(pcl_marks + i * 8) && pl_equal(load64(pcl_argv + i * 8), name) {
            if found { return pcl_fail("duplicate flag"); } found = 1; store64(pcl_marks + i * 8, 1);
        }
        i = i + 1;
    }
    return found;
}
fn pcl_pos() {
    let i = 1;
    while i < pcl_argc {
        if !load64(pcl_marks + i * 8) {
            let arg = load64(pcl_argv + i * 8); store64(pcl_marks + i * 8, 1);
            if pl_starts(arg, "--") { pcl_fail("unknown option"); return ""; } return arg;
        }
        i = i + 1;
    }
    pcl_fail("missing positional argument"); return "";
}
fn pcl_integer(text, lo, hi) {
    if !text { return pcl_fail("missing required option"); }
    let value = pl_integer(text, pl_size(text));
    if pl_bad_number || value < lo || value > hi { return pcl_fail("integer argument is out of range"); } return value;
}
fn pcl_integer_option(name, fallback, lo, hi) { return pcl_integer(pcl_option(name, fallback), lo, hi); }
fn pcl_float(text) {
    if !text { return pcl_fail("missing numeric argument"); }
    let value = pn_parse(text, pl_size(text));
    if pn_error || !f64_is_finite(value) { return pcl_fail("finite number expected"); }
    let word = pb_f64_to_f32(value);
    if !f64_is_finite(pb_f32_to_f64(word)) { return pcl_fail("number is outside protocol f32 range"); } return pb_f32_to_f64(word);
}
fn pcl_float_option(name) { return pcl_float(pcl_option(name, "0")); }
fn pcl_speed() { return pcl_integer_option("--speed", "300", 0, 32767); }
fn pcl_frame() {
    let text = pcl_option("--frame", "base"); if !text { return 0; }
    if pl_equal(text, "base") { return 0; } if pl_equal(text, "tool") { return 1; }
    if pl_equal(text, "yaw-flat") || pl_equal(text, "yawFlat") { return 2; } pcl_fail("frame must be base, tool, or yaw-flat"); return 0;
}
fn pcl_vector(out) {
    let forward = pcl_float_option("--forward"); let back = pcl_float_option("--back");
    let left = pcl_float_option("--left"); let right = pcl_float_option("--right");
    let up = pcl_float_option("--up"); let down = pcl_float_option("--down");
    store64(out, pb_f32_to_f64(pb_f64_to_f32(f64_sub(forward, back))));
    store64(out + 8, pb_f32_to_f64(pb_f64_to_f32(f64_sub(left, right))));
    store64(out + 16, pb_f32_to_f64(pb_f64_to_f32(f64_sub(up, down))));
    let i = 0; while i < 3 { if !f64_is_finite(pb_vget(out, i)) { return pcl_fail("direction is outside protocol f32 range"); } i = i + 1; } return 0;
}
fn pcl_duration(options, stop, joint) {
    let text = pcl_option("--duration-ms", 0);
    if text { pb_vset(options, 7, 1); pb_vset(options, 8, pcl_integer(text, 0, 2147483647)); pb_vset(options, 9, stop); pb_vset(options, 10, joint); } return 0;
}
fn pcl_ids(text, body) {
    if !text { return pcl_fail("--arm-servo-ids is required"); }
    let size = pl_size(text); let at = 0; let i = 0;
    while i < 4 {
        let start = at; while at < size && load8(text + at) != 44 { at = at + 1; }
        let value = pl_integer(text + start, at - start);
        if pl_bad_number || value < 1 || value > 253 { return pcl_fail("exactly four servo IDs in 1..253 are required"); }
        store8(body + i, value); i = i + 1;
        if i < 4 { if at >= size { return pcl_fail("four comma-separated servo IDs are required"); } at = at + 1; }
    }
    if at != size { return pcl_fail("four comma-separated servo IDs are required"); } return 1;
}
fn pcl_build(options, body, vector) {
    let command = pcl_pos(); pb_vset(options, 13, command);
    if pl_equal(command, "ping") { pb_vset(options, 0, 1); pb_vset(options, 2, 1); }
    else if pl_equal(command, "ws-ping") { pb_vset(options, 3, 1); }
    else if pl_equal(command, "config") {
        let action = pcl_pos();
        if pl_equal(action, "get") { pb_vset(options, 0, 25); pb_vset(options, 2, 8); }
        else if pl_equal(action, "set") {
            store8(body, 1); store8(body + 1, pcl_integer_option("--steering-servo-id", "1", 0, 253)); pcl_ids(pcl_option("--arm-servo-ids", 0), body + 2);
            pb_vset(options, 0, 26); pb_vset(options, 1, 6); pb_vset(options, 2, 8);
        } else { pcl_fail("config requires get or set"); }
    }
    else if pl_equal(command, "drive") {
        let action = pcl_pos();
        if pl_equal(action, "stop") { pb_vset(options, 0, 28); }
        else if pl_equal(action, "steer") {
            store8(body, pcl_integer_option("--throttle", 0, -128, 127)); store8(body + 1, pcl_integer_option("--steering", 0, -128, 127)); pb_vset(options, 0, 27); pb_vset(options, 1, 2);
        } else { pcl_fail("drive requires steer or stop"); }
    }
    else if pl_equal(command, "arm") {
        let action = pcl_pos(); pb_vset(options, 13, action);
        if pl_equal(action, "state") { pb_vset(options, 0, 33); pb_vset(options, 1, 2); pb_vset(options, 2, 7); store8(body, 1); store8(body + 1, 1); }
        else if pl_equal(action, "stop") {
            let joint = pcl_option("--joint", 0); if joint { store8(body, pcl_integer(joint, 0, 3)); pb_vset(options, 0, 14); pb_vset(options, 1, 1); } else { pb_vset(options, 0, 31); }
        }
        else if pl_equal(action, "jog") {
            let joint = pcl_integer_option("--joint", 0, 0, 3); store8(body, joint);
            store8(body + 1, pcl_integer_option("--direction", 0, -128, 127)); pb_put16(body + 2, pcl_speed());
            pb_vset(options, 0, 13); pb_vset(options, 1, 4); pcl_duration(options, 14, joint);
        }
        else if pl_equal(action, "hold") { pb_put16(body, pcl_speed()); pb_vset(options, 0, 19); pb_vset(options, 1, 2); }
        else if pl_equal(action, "goto-ticks") || pl_equal(action, "goto-angles") || pl_equal(action, "goto-coords") {
            pb_put16(body, pcl_speed()); let i = 0;
            while i < 4 {
                if pl_equal(action, "goto-ticks") { pb_put32(body + 2 + i * 4, pcl_integer(pcl_pos(), -2147483648, 2147483647)); }
                else { pb_put32(body + 2 + i * 4, pb_f64_to_f32(pcl_float(pcl_pos()))); } i = i + 1;
            }
            let id = 16; if pl_equal(action, "goto-angles") { id = 17; } if pl_equal(action, "goto-coords") { id = 18; }
            pb_vset(options, 0, id); pb_vset(options, 1, 18);
        }
        else if pl_equal(action, "move-tcp") {
            pb_put16(body, pcl_speed()); store8(body + 2, pcl_frame()); pcl_vector(vector); let i = 0;
            while i < 3 { pb_put32(body + 3 + i * 4, pb_f64_to_f32(pb_vget(vector, i))); i = i + 1; }
            pb_vset(options, 0, 23); pb_vset(options, 1, 15);
        }
        else if pl_equal(action, "tcp-jog") {
            let sub = pcl_pos();
            if pl_equal(sub, "stop") { pb_vset(options, 0, 35); }
            else if pl_equal(sub, "start") {
                let speed = pcl_speed(); if !speed { pcl_fail("TCP jog speed must be positive"); }
                store8(body, pcl_frame()); pcl_vector(vector);
                if f64_eq(pb_vget(vector, 0), 0) && f64_eq(pb_vget(vector, 1), 0) && f64_eq(pb_vget(vector, 2), 0) { pcl_fail("TCP jog direction must not be zero"); }
                let i = 0; while i < 3 { pb_put32(body + 1 + i * 4, pb_f64_to_f32(pb_vget(vector, i))); i = i + 1; }
                pb_put32(body + 13, pb_f64_to_f32(f64_from_i64(speed))); pb_vset(options, 0, 34); pb_vset(options, 1, 17);
                pb_vset(options, 11, 1); pb_vset(options, 12, speed); pcl_duration(options, 35, 0);
            } else { pcl_fail("tcp-jog requires start or stop"); }
        }
        else if pl_equal(action, "set-joint-tick") {
            store8(body, pcl_integer_option("--joint", 0, 0, 3)); pb_put16(body + 1, pcl_speed());
            pb_put32(body + 3, pcl_integer_option("--tick", 0, -2147483648, 2147483647)); pb_vset(options, 0, 20); pb_vset(options, 1, 7);
        }
        else if pl_equal(action, "clear-faults") {
            let joint = pcl_option("--joint", 0); let value = 255; if joint { value = pcl_integer(joint, 0, 3); }
            store8(body, value); pb_vset(options, 0, 24); pb_vset(options, 1, 1);
        }
        else if pl_equal(action, "servo-set") {
            store8(body, pcl_integer_option("--servo-id", 0, 1, 253)); pb_put16(body + 1, pcl_integer_option("--angle-deg", 0, 0, 65535));
            pb_put16(body + 3, pcl_integer_option("--duration-ms", "500", 0, 65535)); pb_vset(options, 0, 32); pb_vset(options, 1, 5);
        } else { pcl_fail("unknown arm command"); }
    } else { pcl_fail("command must be ping, ws-ping, config, arm, or drive"); }
    let i = 1; while i < pcl_argc { if !load64(pcl_marks + i * 8) { pcl_fail("unknown or extra argument"); } i = i + 1; }
    return !pcl_error;
}
fn pcl_fixed(builder, word, hundredths) {
    if !f64_is_finite(word) || f64_gt(f64_magnitude(word), 0x426d1a94a2000000) { return pl_float(builder, word); }
    let scale = 10; if hundredths { scale = 100; }
    let value = f64_to_i64_round(f64_mul(f64_magnitude(word), f64_from_i64(scale)));
    if f64_sign(word) { pl_char(builder, 45); } pl_uint(builder, value / scale); pl_char(builder, 46);
    if hundredths { pl_char(builder, 48 + (value % 100) / 10); } return pl_char(builder, 48 + value % 10);
}
fn pcl_coordinates(builder, data, json) {
    if !load8(data) { return pl_text(builder, "null"); }
    if json { pl_char(builder, 91); } let i = 0;
    while i < 3 { if i { pl_char(builder, 44); } let value = pb_read_float(data + 1 + i * 4); if json { pl_float(builder, value); } else { pcl_fixed(builder, value, 0); } i = i + 1; }
    if json { return pl_char(builder, 93); } return 0;
}
fn pcl_state(builder, data, size, json, joints) {
    if size < 4 || pb_u16(data) != 1 || load8(data + 2) != 7 { return pcl_fail("invalid arm telemetry frame"); }
    let count = load8(data + 3); if count > 64 { return pcl_fail("joint telemetry count exceeds limit"); }
    let at = 4; let i = 0;
    while i < count {
        if size - at < 25 { return pcl_fail("truncated joint telemetry"); }
        let j = joints + i * 128; pb_zero(j, 128);
        pb_vset(j, 0, load8(data + at)); pb_vset(j, 1, load8(data + at + 1)); pb_vset(j, 2, pb_i32(pb_u32(data + at + 2)));
        pb_vset(j, 3, pb_i32(pb_u32(data + at + 6))); pb_vset(j, 4, pb_i16(pb_u16(data + at + 10)));
        pb_vset(j, 5, pb_i32(pb_u32(data + at + 12))); pb_vset(j, 6, pb_i32(pb_u32(data + at + 16))); pb_vset(j, 7, pb_read_float(data + at + 20));
        let n = load8(data + at + 24); if size - at - 25 < n || !ph_utf8(data + at + 25, n) { return pcl_fail("invalid telemetry fault string"); }
        pb_vset(j, 8, data + at + 25); pb_vset(j, 9, n); at = at + 25 + n; i = i + 1;
    }
    if size - at < 13 { return pcl_fail("missing telemetry coordinates"); }
    let current = data + at; at = at + 13; let target = 0;
    if at < size && load8(data + at) == 1 {
        at = at + 1; i = 0;
        while i < count {
            if size - at < 5 { return pcl_fail("truncated target-angle extension"); }
            let j = joints + i * 128; pb_vset(j, 10, load8(data + at) != 0); pb_vset(j, 11, pb_read_float(data + at + 1)); at = at + 5; i = i + 1;
        }
        if size - at < 13 { return pcl_fail("truncated target-coordinate extension"); } target = data + at;
    }
    if json { pl_text(builder, "{\"joints\":["); } else { pl_text(builder, "servo\tonline\tfeedback\ttick\ttarget\ttarget_angle\tspeed\tlimits\tangle\tfault\n"); }
    i = 0;
    while i < count {
        let j = joints + i * 128; let flags = pb_vget(j, 1);
        if json {
            if i { pl_char(builder, 44); } pl_text(builder, "{\"servo_id\":"); pl_int(builder, pb_vget(j, 0));
            pl_text(builder, ",\"online\":"); pj_bool_text(builder, flags & 1); pl_text(builder, ",\"has_feedback\":"); pj_bool_text(builder, flags & 2);
            pl_text(builder, ",\"tick\":"); pl_int(builder, pb_vget(j, 2)); pl_text(builder, ",\"target_tick\":"); if flags & 8 { pl_int(builder, pb_vget(j, 3)); } else { pl_text(builder, "null"); }
            pl_text(builder, ",\"target_angle_deg\":"); if pb_vget(j, 10) { pl_float(builder, pb_vget(j, 11)); } else { pl_text(builder, "null"); }
            pl_text(builder, ",\"speed\":"); pl_int(builder, pb_vget(j, 4)); pl_text(builder, ",\"limit_min\":"); pl_int(builder, pb_vget(j, 5));
            pl_text(builder, ",\"limit_max\":"); pl_int(builder, pb_vget(j, 6)); pl_text(builder, ",\"angle_deg\":"); pl_float(builder, pb_vget(j, 7));
            pl_text(builder, ",\"fault\":"); if pb_vget(j, 9) { pj_quote(builder, pb_vget(j, 8), pb_vget(j, 9)); } else { pl_text(builder, "null"); } pl_char(builder, 125);
        } else {
            pl_uint(builder, pb_vget(j, 0)); pl_char(builder, 9); if flags & 1 { pl_text(builder, "yes"); } else { pl_text(builder, "no"); }
            pl_char(builder, 9); if flags & 2 { pl_text(builder, "yes"); } else { pl_text(builder, "no"); } pl_char(builder, 9); pl_int(builder, pb_vget(j, 2)); pl_char(builder, 9);
            if flags & 8 { pl_int(builder, pb_vget(j, 3)); } else { pl_char(builder, 45); } pl_char(builder, 9);
            if pb_vget(j, 10) { pcl_fixed(builder, pb_vget(j, 11), 1); } else { pl_char(builder, 45); } pl_char(builder, 9);
            pl_int(builder, pb_vget(j, 4)); pl_char(builder, 9); pl_int(builder, pb_vget(j, 5)); pl_text(builder, ".."); pl_int(builder, pb_vget(j, 6)); if flags & 4 { pl_char(builder, 33); }
            pl_char(builder, 9); pcl_fixed(builder, pb_vget(j, 7), 1); pl_char(builder, 9);
            if pb_vget(j, 9) { pl_append(builder, pb_vget(j, 8), pb_vget(j, 9)); } else if flags & 16 { pl_text(builder, "unknown"); } else { pl_char(builder, 45); } pl_char(builder, 10);
        }
        i = i + 1;
    }
    if json {
        pl_text(builder, "],\"coords_mm\":"); pcl_coordinates(builder, current, 1);
        pl_text(builder, ",\"target_coords_mm\":"); if target { pcl_coordinates(builder, target, 1); } else { pl_text(builder, "null"); } pl_text(builder, "}\n");
    } else {
        if load8(current) { pl_text(builder, "coords_mm="); pcl_coordinates(builder, current, 0); pl_char(builder, 10); }
        if target && load8(target) { pl_text(builder, "target_coords_mm="); pcl_coordinates(builder, target, 0); pl_char(builder, 10); }
    }
    return 1;
}
fn pcl_config(builder, data, size, json) {
    if size != 9 || pb_u16(data) != 1 || load8(data + 2) != 8 || load8(data + 3) != 1 { return pcl_fail("invalid config response"); }
    if json { pl_text(builder, "{\"steering_servo_id\":"); } else { pl_text(builder, "steering_servo_id="); } pl_uint(builder, load8(data + 4));
    if json { pl_text(builder, ",\"arm_servo_ids\":["); } else { pl_text(builder, "\narm_servo_ids="); }
    let i = 0; while i < 4 { if i { pl_char(builder, 44); } pl_uint(builder, load8(data + 5 + i)); i = i + 1; }
    if json { pl_text(builder, "]}\n"); } else { pl_char(builder, 10); } return 1;
}
fn pcl_usage() {
    return pl_print(1, "Usage: puppybot [--url ws://HOST:PORT/ws] [--timeout-ms N] [--json] COMMAND\n\n  ping | ws-ping\n  config get | config set --steering-servo-id ID --arm-servo-ids 1,2,3,4\n  drive steer --throttle PERCENT --steering PERCENT | drive stop\n  arm state | arm stop [--joint N] | arm hold [--speed N]\n  arm jog --joint N --direction -1|1 [--speed N] [--duration-ms N]\n  arm goto-ticks T0 T1 T2 T3 | arm goto-angles D0 D1 D2 D3\n  arm goto-coords X Y Z TOOL_DEG | arm set-joint-tick --joint N --tick T\n  arm move-tcp | arm tcp-jog start|stop [--frame base|tool|yaw-flat]\n      [--forward N] [--back N] [--left N] [--right N] [--up N] [--down N]\n  arm clear-faults [--joint N]\n  arm servo-set --servo-id N --angle-deg N [--duration-ms N]\n");
}
fn pcl_execute(options, body, scratch, builder, joints) {
    let timeout = pb_vget(options, 5); let expect = pb_vget(options, 2); let json = pb_vget(options, 4);
    if !pcc_connect(pb_vget(options, 6), timeout) { return 0; }
    if pb_vget(options, 3) {
        if !pcc_send(1, "ping", 4, pl_now() + timeout) || !pcc_receive(pl_now() + timeout) { return 0; }
        if pcc_opcode != 1 || !ph_utf8(pcc_message, pcc_size) { return pcc_fail("text ping did not return text"); }
        if json { pl_text(builder, "{\"text\":"); pj_quote(builder, pcc_message, pcc_size); pl_text(builder, "}\n"); }
        else { pl_append(builder, pcc_message, pcc_size); pl_char(builder, 10); } return 1;
    }
    if pb_vget(options, 11) {
        pb_put16(scratch, pb_vget(options, 12)); if !pcc_protocol(12, scratch, 2, scratch + 128, timeout) { return 0; }
    }
    if !pcc_protocol(pb_vget(options, 0), body, pb_vget(options, 1), scratch + 128, timeout) { return 0; }
    if expect {
        if !pcc_response(expect, timeout) { return 0; }
        if expect == 1 { if json { pl_text(builder, "{\"pong\":true}\n"); } else { pl_text(builder, "pong\n"); } return 1; }
        if expect == 8 { return pcl_config(builder, pcc_message, pcc_size, json); }
        return pcl_state(builder, pcc_message, pcc_size, json, joints);
    }
    let acknowledged = pcc_barrier(scratch, timeout);
    if !acknowledged && !(pb_vget(options, 7) && pcc_cancelled) { return 0; }
    if pb_vget(options, 7) {
        if !pcc_cancelled { pcc_delay(pb_vget(options, 8)); } pcc_ignore_signal = 1; let stop = pb_vget(options, 9); let n = 0;
        if stop == 14 { store8(scratch, pb_vget(options, 10)); n = 1; }
        if !pcc_protocol(stop, scratch, n, scratch + 128, timeout) || !pcc_barrier(scratch, timeout) { return 0; }
    }
    if json { pl_text(builder, "{\"sent\":true,\"command\":"); pj_text(builder, pb_vget(options, 13)); pl_text(builder, "}\n"); }
    else { pl_text(builder, "sent "); pl_text(builder, pb_vget(options, 13)); pl_char(builder, 10); } return 1;
}
fn main(argc, argv) {
    if !pl_init() { return 1; }
    let i = 1; while i < argc { if pl_equal(load64(argv + i * 8), "--help") || pl_equal(load64(argv + i * 8), "-h") { pcl_usage(); return 0; } i = i + 1; }
    if argc < 2 { pcl_usage(); return 2; }
    pcl_argc = argc; pcl_argv = argv; pcl_marks = alloc(argc * 8);
    let options = alloc(128); let body = alloc(128); let vector = alloc(32); let scratch = alloc(512);
    let builder = alloc(32); let output = alloc(65536); let joints = alloc(8192);
    if pcl_marks <= 0 || options <= 0 || body <= 0 || vector <= 0 || scratch <= 0 || builder <= 0 || output <= 0 || joints <= 0 { return 1; }
    pb_vset(options, 6, pcl_option("--url", "ws://127.0.0.1:8080/ws"));
    pb_vset(options, 5, pcl_integer_option("--timeout-ms", "1500", 1, 300000)); pb_vset(options, 4, pcl_boolean("--json"));
    if !pcl_build(options, body, vector) { pl_print(2, "puppybot: "); if pcl_message { pl_print(2, pcl_message); } pl_print(2, "\n"); return 2; }
    pl_builder(builder, output, 65536); let ok = pcl_execute(options, body, scratch, builder, joints); pcc_close();
    if !ok || pcl_error || load64(builder + 24) {
        pl_print(2, "puppybot: "); if pcl_message { pl_print(2, pcl_message); } else if pcc_error { pl_print(2, pcc_error); } else { pl_print(2, "operation failed"); } pl_print(2, "\n");
        if pcc_cancelled { return 128 + pcc_cancelled; } return 1;
    }
    pl_write(1, output, load64(builder + 8)); if pcc_cancelled { return 128 + pcc_cancelled; } return 0;
}
