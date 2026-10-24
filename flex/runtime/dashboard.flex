// Monolith rendering/forms over the runtime's bounded, nonblocking transport.
// No Monolith socket writer runs on the servo loop; slow clients use pnet queues.
import "monolith";
import "assets.flex";
import "views.flex";

global pu_app = 0;
global pu_now = 0;
global pu_mark = 0;
global pu_next = 0;
global pu_heartbeat = 0;
global pu_lease = 0;
global pu_hold = 0;
global pu_deadline = 0;

// The runtime owns startup and invalidation instead of mono_run's socket loop.
fn app_init(path) { return 0; }
fn app_tick() { return 0; }

fn pu_end() {
    pu_lease = 0; pu_hold = 0; pu_deadline = 0;
    if pb_vget(pu_app, 37) { return pr_guard_abort(pu_app, pu_now); }
    return pr_stop(pu_app, pu_now);
}
fn pu_command(path, body) {
    let b = pn_builder + 32; pl_builder(b, pn_body, 65536);
    let code = pr_request(pu_app, "POST", path, body, m_len(body), b, pu_now);
    if code != 200 {
        let root = pj_parse(pn_body, load64(b + 8)); let error = pj_string_field(root, "error");
        if !pj_error { pr_last(pu_app, error); } else { pr_last(pu_app, "Command rejected"); }
    } return code;
}
fn pu_jog(id) {
    if id >= 1 && id <= 4 {
        let action = "forward"; if id == 2 { action = "back"; } if id == 3 { action = "left"; } if id == 4 { action = "right"; }
        return pu_command("/api/drive", m_cat(m_cat("{\"action\":\"", action), "\"}"));
    }
    if id >= 10 && id <= 17 {
        let path = m_cat(m_cat("/api/arm/joints/", m_int((id - 10) / 2)), "/spin");
        let direction = "-1"; if id % 2 { direction = "1"; }
        return pu_command(path, m_cat(m_cat("{\"direction\":", direction), "}"));
    }
    if id >= 20 && id <= 25 {
        let direction = "forward"; if id == 21 { direction = "back"; } if id == 22 { direction = "left"; }
        if id == 23 { direction = "right"; } if id == 24 { direction = "up"; } if id == 25 { direction = "down"; }
        let frame = "base"; if pb_vget(pu_app, 24) { frame = "tool"; }
        return pu_command("/api/arm/tcp-jog/start", m_cat(m_cat(m_cat(m_cat("{\"frame\":\"", frame), "\",\"direction\":\""), direction), "\"}"));
    } return 422;
}
fn pu_renew(id) {
    // Renew admission/deadmen without issuing a new start (which clears faults
    // and the joint stall timer). A held button must never clear its own fault.
    if !pu_ready() { pr_last(pu_app, "Jog stopped: outputs are unavailable"); return 409; }
    let robot = load64(pu_app);
    if id >= 10 && id <= 17 {
        let joint = pb_joint(robot, (id - 10) / 2);
        if pb_j(joint, PB_J_FAULT) || pb_a(robot, PB_A_MODE) != 1 { pr_last(pu_app, "Joint jog stopped; check feedback, limits and faults"); return 409; }
        pb_as(robot, PB_A_LAST_CMD, pu_now); pb_vset(pu_app, 16, pu_now); return 200;
    }
    if id >= 20 && id <= 25 {
        let i = 0;
        while i < 4 { if pb_j(pb_joint(robot, i), PB_J_FAULT) { pr_last(pu_app, "TCP jog stopped by a joint fault"); return 409; } i = i + 1; }
        if pb_a(robot, PB_A_MODE) != 3 { pr_last(pu_app, "TCP jog has stopped"); return 409; }
        pb_as(robot, PB_A_LAST_CMD, pu_now); pb_vset(pu_app, 22, pu_now); return 200;
    }
    return pu_jog(id);
}
fn pu_json_fields(names, count) {
    let b = m_buffer(); m_text(b, "{"); let i = 0;
    while i < count {
        let name = load64(names + i * 8); if i { m_text(b, ","); }
        m_escape(b, name, 1); m_text(b, ":"); let value = mono_field(name);
        if m_eq(name, "frame") { m_escape(b, value, 1); }
        else {
            let node = pj_parse(value, m_len(value)); let kind = pj_kind(node);
            if !pj_error && (kind == 1 || kind == 6 || kind == 7) { m_text(b, value); }
            else { m_escape(b, value, 1); }
        } i = i + 1;
    }
    m_text(b, "}"); return m_data(b);
}
fn app_action(action, id) {
    if m_eq(action, "release") {
        let lease = m_number(mono_field("lease")); if lease > 0 && lease == pu_lease { pu_end(); } return 200;
    }
    if m_eq(action, "jog") || m_eq(action, "renew") {
        let lease = m_number(mono_field("lease")); if lease <= 0 { return 422; }
        if m_eq(action, "renew") && (lease != pu_lease || id != pu_hold || pu_now >= pu_deadline) { return 409; }
        if pu_lease && (lease != pu_lease || id != pu_hold) { return 409; }
        if !pu_lease { pu_end(); }
        let code = 0; if pu_lease { code = pu_renew(id); } else { code = pu_jog(id); }
        if code == 200 { pu_lease = lease; pu_hold = id; pu_deadline = pu_now + 500; }
        else { pu_end(); } return code;
    }
    pu_end();
    if m_eq(action, "stop") { pr_last(pu_app, "Stopped all motion"); return 200; }
    if m_eq(action, "enable") { return pu_command("/api/control/enable", "{}"); }
    if m_eq(action, "disable") { return pu_command("/api/control/disable", "{}"); }
    if m_eq(action, "hold") { return pu_command("/api/arm/hold", "{}"); }
    if m_eq(action, "clear-faults") { return pu_command("/api/arm/clear-faults", "{}"); }
    if m_eq(action, "save") { return pu_command("/api/calibration/save", "{}"); }
    if m_eq(action, "default") { return pu_command("/api/arm/goto-default", "{}"); }
    if m_eq(action, "speed") { let names = m_take(8); store64(names, "speed"); return pu_command("/api/arm/speed", pu_json_fields(names, 1)); }
    if m_eq(action, "frame") { let names = m_take(8); store64(names, "frame"); return pu_command("/api/arm/tcp-frame", pu_json_fields(names, 1)); }
    if m_eq(action, "angles") {
        let names = m_take(32); store64(names, "yawDeg"); store64(names + 8, "shoulderDeg"); store64(names + 16, "elbowDeg"); store64(names + 24, "wristDeg");
        return pu_command("/api/arm/goto-angles", pu_json_fields(names, 4));
    }
    if m_eq(action, "coordinates") {
        let names = m_take(32); store64(names, "xMm"); store64(names + 8, "yMm"); store64(names + 16, "zMm"); store64(names + 24, "toolPhiDeg");
        return pu_command("/api/arm/coordinates/move", pu_json_fields(names, 4));
    }
    if id >= 1 && id <= 4 {
        let path = m_cat("/api/arm/joints/", m_int(id - 1));
        if m_eq(action, "zero") { return pu_command(m_cat(path, "/zero"), "{}"); }
        if m_eq(action, "reference") { let names = m_take(8); store64(names, "angleDeg"); return pu_command(m_cat(path, "/reference"), pu_json_fields(names, 1)); }
        if m_eq(action, "limits") { let names = m_take(16); store64(names, "minTick"); store64(names + 8, "maxTick"); return pu_command(m_cat(path, "/limits"), pu_json_fields(names, 2)); }
    } return 422;
}
fn pu_route(path) {
    return pl_equal(path, "/") || pl_equal(path, "/client.js") || pl_equal(path, "/style.css") || pl_equal(path, "/events") || pl_equal(path, "/action");
}
fn pu_reply(c, code, type, body, now) { return pnet_reply(c, code, type, body, m_len(body), now); }
fn pu_request(c, now) {
    let slot = m_take(64); pb_zero(slot, 64); store64(slot + 8, c + 512); store64(slot + 16, pb_vget(c, 2)); store64(slot + 32, pb_vget(c, 10));
    let code = sv_parse(slot);
    if code != 200 { return pu_reply(c, code, "application/json", "{\"error\":\"Invalid dashboard request\"}", now); }
    if m_eq(sv_method, "GET") {
        if m_eq(sv_path, "/") { return pu_reply(c, 200, "text/html; charset=utf-8", sv_html(), now); }
        if m_eq(sv_path, "/client.js") { return pu_reply(c, 200, "text/javascript; charset=utf-8", m_cat(mono_client_js(), pu_controls_js()), now); }
        if m_eq(sv_path, "/style.css") { return pu_reply(c, 200, "text/css; charset=utf-8", pu_styles(), now); }
        if m_eq(sv_path, "/events") {
            let headers = "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\nConnection: close\r\nX-Accel-Buffering: no\r\n\r\n";
            pnet_queue(c, headers, m_len(headers), now); let message = sv_event(mono_compiled_diff(0, sv_root, 0, sv_index), 1);
            if pnet_queue(c, message, m_len(message), now) == 0 { pb_vset(c, 1, 5); } return 0;
        } return pu_reply(c, 404, "application/json", "{\"error\":\"Unknown dashboard resource\"}", now);
    }
    if !m_eq(sv_method, "POST") { return pu_reply(c, 405, "application/json", "{\"error\":\"Use GET or POST\"}", now); }
    if !m_eq(sv_path, "/action") { return pu_reply(c, 404, "application/json", "{\"error\":\"Unknown action endpoint\"}", now); }
    if !m_eq(sv_type, "application/x-www-form-urlencoded") { return pu_reply(c, 415, "application/json", "{\"error\":\"Expected form data\"}", now); }
    if sv_origin && !m_eq(sv_origin, m_cat("http://", sv_host)) { return pu_reply(c, 403, "application/json", "{\"error\":\"Origin rejected\"}", now); }
    if !sv_form(c + 512 + pb_vget(c, 10), sv_length) { return pu_reply(c, 400, "application/json", "{\"error\":\"Invalid form data\"}", now); }
    if !m_eq(sv_form_token, sv_token) { return pu_reply(c, 403, "application/json", "{\"error\":\"Action token rejected\"}", now); }
    code = app_action(sv_action, sv_id); pu_next = 0;
    let b = m_buffer(); m_text(b, "{\"ok\":"); if code == 200 { m_text(b, "true"); } else { m_text(b, "false,\"error\":"); m_escape(b, pu_app + 512, 1); } m_text(b, "}");
    return pu_reply(c, code, "application/json", m_data(b), now);
}
fn pu_init(app, port) {
    pu_app = app; mono_name = "PuppyBot"; sv_port = port;
    let random = alloc(16); let i = 0;
    while i < 16 { let n = syscall(318, random + i, 16 - i, 0, 0, 0, 0); if n > 0 { i = i + n; } else if n != -4 { return 0; } }
    sv_token = alloc(33); let hex = "0123456789abcdef"; i = 0;
    while i < 16 { let byte = load8(random + i); store8(sv_token + i * 2, load8(hex + (byte >> 4))); store8(sv_token + i * 2 + 1, load8(hex + (byte & 15))); i = i + 1; } store8(sv_token + 32, 0);
    sv_refresh(); pu_mark = m_mark(); return 1;
}
fn pu_poll(app, now) {
    pu_now = now;
    if pu_lease && now >= pu_deadline { pu_end(); pr_last(app, "Jog stopped: button lease expired"); }
    // A stop from another API/wire client must also revoke browser renewals.
    if pu_lease {
        let active = pb_vget(app, 17);
        if pu_hold <= 4 { active = pb_vget(app, 9); }
        if pu_hold >= 10 && pu_hold <= 17 { active = pb_vget(app, 13); }
        if !active { pu_lease = 0; pu_hold = 0; pu_deadline = 0; }
    }
    let i = 0;
    while i < 32 {
        let c = pn_clients + i * 65536;
        if load64(c) >= 0 && pb_vget(c, 1) == 1 && pu_route(c + 160) { pu_request(c, now); }
        i = i + 1;
    }
    if now >= pu_next {
        pu_next = now + 200; let patch = sv_refresh();
        sv_revision = sv_revision + 1; let message = sv_event(patch, 0); i = 0;
        while i < 32 { let c = pn_clients + i * 65536; if load64(c) >= 0 && pb_vget(c, 1) == 5 { pnet_queue(c, message, m_len(message), now); } i = i + 1; }
    }
    if now >= pu_heartbeat {
        pu_heartbeat = now + 15000; i = 0;
        while i < 32 { let c = pn_clients + i * 65536; if load64(c) >= 0 && pb_vget(c, 1) == 5 { pnet_queue(c, ": keepalive\n\n", 13, now); } i = i + 1; }
    }
    m_reset(pu_mark); return 0;
}
