// Bounded nonblocking HTTP/WebSocket server. Each connection owns its buffers;
// incomplete requests and slow writes never enter a blocking network loop.
import "../host/http.flex";
import "app.flex";

global pn_clients = 0;
global pn_listener = -1;
global pn_port = 0;
global pn_head = 0;
global pn_body = 0;
global pn_builder = 0;
global pn_wire_scratch = 0;

fn pnet_close(c) { let fd = load64(c); if fd >= 0 { syscall(3, fd, 0, 0, 0, 0, 0); } store64(c, -1); return 0; }
fn pnet_queue(c, data, size, now) {
    let used = pb_vget(c, 3); let sent = pb_vget(c, 4);
    if sent { pb_copy(c + 16384, c + 16384 + sent, used - sent); used = used - sent; pb_vset(c, 4, 0); }
    if size < 0 || size > 32768 - used { pnet_close(c); return -1; }
    if !used { pb_vset(c, 6, now + 2000); }
    pb_copy(c + 16384 + used, data, size); pb_vset(c, 3, used + size); return 0;
}
fn pnet_ws_send(c, opcode, data, size, now) {
    let n = pw_frame(pn_head, 4096, opcode, data, size, 0, 0); if n < 0 { return -1; } return pnet_queue(c, pn_head, n, now);
}
fn pnet_ws_close(c, code, now) {
    store8(pn_body, code >> 8); store8(pn_body + 1, code); pnet_ws_send(c, 8, pn_body, 2, now); pb_vset(c, 1, 3); return 0;
}
fn pnet_reply(c, status, content_type, body, size, now) {
    pl_builder(pn_builder, pn_head, 4096); pl_text(pn_builder, "HTTP/1.1 "); pl_text(pn_builder, ph_status(status));
    pl_text(pn_builder, "\r\nContent-Type: "); pl_text(pn_builder, content_type);
    pl_text(pn_builder, "\r\nContent-Length: "); pl_uint(pn_builder, size);
    pl_text(pn_builder, "\r\nConnection: close\r\nCache-Control: no-store\r\n");
    if status == 405 { pl_text(pn_builder, "Allow: GET, POST\r\n"); }
    if status == 426 { pl_text(pn_builder, "Sec-WebSocket-Version: 13\r\n"); }
    pl_text(pn_builder, "\r\n"); pnet_queue(c, pn_head, load64(pn_builder + 8), now); pnet_queue(c, body, size, now); pb_vset(c, 1, 3); return 0;
}
fn pnet_error(c, status, message, now) {
    let builder = pn_builder + 32; pl_builder(builder, pn_body, 65536);
    pl_text(builder, "{\"ok\":false,\"error\":"); pj_text(builder, message); pl_text(builder, "}");
    return pnet_reply(c, status, "application/json; charset=utf-8", pn_body, load64(builder + 8), now);
}
fn pnet_init(address) {
    pn_clients = alloc(32 * 65536); pn_head = alloc(4096); pn_body = alloc(65536); pn_builder = alloc(64); pn_wire_scratch = alloc(2048);
    if pn_clients <= 0 || pn_head <= 0 || pn_body <= 0 || pn_builder <= 0 || pn_wire_scratch <= 0 { return -1; }
    let i = 0; while i < 32 { store64(pn_clients + i * 65536, -1); i = i + 1; }
    let port = pl_scratch + 384; pn_listener = pl_listen(address, port); pn_port = load64(port); return pn_listener;
}
fn pnet_accept(now) {
    let attempts = 0;
    while attempts < 8 {
        let address = pl_scratch + 384; store64(address + 32, 16);
        let fd = syscall(288, pn_listener, address, address + 32, 0x80800, 0, 0);
        if fd < 0 { return 0; } let i = 0; let chosen = 0;
        while i < 32 && !chosen { let c = pn_clients + i * 65536; if load64(c) < 0 { chosen = c; } i = i + 1; }
        if !chosen { syscall(3, fd, 0, 0, 0, 0, 0); }
        else { pb_zero(chosen, 512); store64(chosen, fd); pb_vset(chosen, 5, now + 2000); pb_copy(chosen + 448, address, 16); }
        attempts = attempts + 1;
    }
    return 0;
}
fn pnet_consume(c, size) {
    let n = pb_vget(c, 2); pb_copy(c + 512, c + 512 + size, n - size); pb_vset(c, 2, n - size); return 0;
}
fn pnet_http(c, now) {
    let data = c + 512; let size = pb_vget(c, 2); let end = pb_vget(c, 10);
    if !end {
        end = ph_find(data, size, "\r\n\r\n", 4);
        if end < 0 { if size == 12288 { pnet_error(c, 431, "HTTP headers exceed 12 KiB", now); } return 0; }
        end = end + 4; if !ph_headers_valid(data, end) { return pnet_error(c, 400, "invalid HTTP headers", now); }
        let line = ph_find(data, end, "\r\n", 2); let first = ph_find(data, line, " ", 1);
        if first < 1 || first > 15 { return pnet_error(c, 400, "invalid HTTP method", now); }
        let second = ph_find(data + first + 1, line - first - 1, " ", 1);
        if second < 1 || second > 255 { return pnet_error(c, 400, "invalid HTTP target", now); }
        let version = data + first + second + 2; let version_size = line - first - second - 2;
        if version_size != 8 || (!pl_case_equal(version, 8, "HTTP/1.1") && !pl_case_equal(version, 8, "HTTP/1.0")) { return pnet_error(c, 400, "unsupported HTTP version", now); }
        let i = 0; while i < first { if !ph_token_char(load8(data + i)) { return pnet_error(c, 400, "invalid HTTP method", now); } i = i + 1; }
        pb_copy(c + 128, data, first); store8(c + 128 + first, 0);
        pb_copy(c + 160, data + first + 1, second); store8(c + 160 + second, 0);
        if load8(c + 160) != 47 { return pnet_error(c, 400, "origin-form HTTP target required", now); }
        i = 0; while i < second { let byte = load8(c + 160 + i); if byte <= 32 || byte == 127 { return pnet_error(c, 400, "invalid HTTP target", now); } i = i + 1; }
        let question = ph_find(c + 160, second, "?", 1); if question >= 0 { store8(c + 160 + question, 0); }
        let host = ph_header(data, end, "host"); if ph_duplicates || (load8(version + 7) == 49 && (!host || !ph_value_size)) { return pnet_error(c, 400, "one Host header required", now); }
        if ph_header(data, end, "transfer-encoding") { return pnet_error(c, 501, "HTTP transfer encoding is unsupported", now); }
        let content = ph_header(data, end, "content-length"); let length = 0;
        if content { length = pl_unsigned_parse(content, ph_value_size); if ph_duplicates || pl_bad_number || length < 0 { return pnet_error(c, 400, "invalid Content-Length", now); } }
        if length > 8192 || length + end > 12288 { return pnet_error(c, 413, "HTTP body exceeds request limit", now); }
        let upgrade = ph_header(data, end, "upgrade"); let wants_ws = upgrade != 0;
        if wants_ws {
            if ph_duplicates || !pl_case_equal(upgrade, ph_value_size, "websocket") || !pl_equal(c + 128, "GET") || !pl_equal(c + 160, "/ws") || length || load8(version + 7) != 49 { return pnet_error(c, 400, "invalid WebSocket upgrade", now); }
            let connection = ph_header(data, end, "connection"); if !connection || !ph_has_token(connection, ph_value_size, "upgrade") { return pnet_error(c, 400, "Connection upgrade token required", now); }
            let ws_version = ph_header(data, end, "sec-websocket-version");
            if !ws_version || ph_duplicates || !pl_case_equal(ws_version, ph_value_size, "13") { return pnet_error(c, 426, "WebSocket version 13 required", now); }
            let key = ph_header(data, end, "sec-websocket-key");
            if !key || ph_duplicates || !pw_accept(pn_body, key, ph_value_size, pn_wire_scratch) { return pnet_error(c, 400, "invalid WebSocket key", now); }
            pl_builder(pn_builder, pn_head, 4096); pl_text(pn_builder, "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ");
            pl_append(pn_builder, pn_body, 28); pl_text(pn_builder, "\r\n\r\n"); pnet_queue(c, pn_head, load64(pn_builder + 8), now);
            pnet_consume(c, end); pb_vset(c, 1, 2); return 0;
        }
        pb_vset(c, 9, length); pb_vset(c, 10, end);
    }
    if size >= end + pb_vget(c, 9) { pb_vset(c, 1, 1); } return 0;
}
fn pnet_websocket(c, now) {
    let iterations = 0;
    while pb_vget(c, 2) && !pb_vget(c, 13) && pb_vget(c, 1) == 2 && iterations < 16 {
        iterations = iterations + 1;
        let data = c + 512; let meta = c + 15360; let n = pw_parse(data, pb_vget(c, 2), 1, meta);
        if !n { return 0; } if n < 0 { return pnet_ws_close(c, -n, now); }
        let opcode = load64(meta); let fin = load64(meta + 8); let header = load64(meta + 16); let size = load64(meta + 24); let key = load64(meta + 32);
        let payload = data + header; let i = 0;
        while i < size { store8(payload + i, load8(payload + i) ^ ((key >> ((i % 4) * 8)) & 255)); i = i + 1; }
        if opcode >= 8 {
            if opcode == 9 { pnet_ws_send(c, 10, payload, size, now); }
            if opcode == 8 {
                if size == 1 { return pnet_ws_close(c, 1002, now); }
                if size >= 2 {
                    let code = (load8(payload) << 8) | load8(payload + 1);
                    if code < 1000 || code >= 5000 || code == 1004 || code == 1005 || code == 1006 || code == 1015 || (code > 1015 && code < 3000) { return pnet_ws_close(c, 1002, now); }
                    if !ph_utf8(payload + 2, size - 2) { return pnet_ws_close(c, 1007, now); }
                }
                pnet_ws_send(c, 8, payload, size, now); pb_vset(c, 1, 3);
            }
        } else {
            let fragment = pb_vget(c, 11); let used = pb_vget(c, 12);
            if (opcode == 0 && !fragment) || (opcode != 0 && fragment) { return pnet_ws_close(c, 1002, now); }
            if opcode { fragment = opcode; used = 0; pb_vset(c, 11, fragment); }
            if size > 2048 - used { return pnet_ws_close(c, 1009, now); }
            pb_copy(c + 13000 + used, payload, size); used = used + size; pb_vset(c, 12, used);
            if fin {
                if fragment == 1 {
                    if !ph_utf8(c + 13000, used) { return pnet_ws_close(c, 1007, now); }
                    if used == 4 && load8(c + 13000) == 112 && load8(c + 13001) == 105 && load8(c + 13002) == 110 && load8(c + 13003) == 103 { pnet_ws_send(c, 1, "pong", 4, now); }
                } else { pb_vset(c, 13, 2); pb_vset(c, 14, used); }
                pb_vset(c, 11, 0); pb_vset(c, 12, 0);
            }
        }
        pnet_consume(c, n);
    }
    return 0;
}
fn pnet_io(now) {
    pnet_accept(now); let i = 0;
    while i < 32 {
        let c = pn_clients + i * 65536; let fd = load64(c);
        if fd >= 0 {
            let mode = pb_vget(c, 1);
            if mode == 0 && now >= pb_vget(c, 5) { pnet_error(c, 408, "HTTP request timed out", now); mode = pb_vget(c, 1); }
            if (mode == 0 || mode == 2) && !pb_vget(c, 13) && !pb_vget(c, 15) {
                let size = pb_vget(c, 2); let room = 12288 - size;
                if room <= 0 { if mode == 0 { pnet_error(c, 431, "HTTP request buffer is full", now); } else { pnet_ws_close(c, 1009, now); } }
                else {
                    let n = syscall(0, fd, c + 512 + size, pb_min(room, 4096), 0, 0, 0);
                    if n > 0 { pb_vset(c, 2, size + n); }
                    else if n == 0 { pb_vset(c, 15, 1); }
                    else if n != -11 && n != -4 { pnet_close(c); }
                }
            }
            if load64(c) >= 0 {
                if pb_vget(c, 1) == 0 { pnet_http(c, now); }
                if pb_vget(c, 1) == 2 { pnet_websocket(c, now); }
                let size = pb_vget(c, 3); let sent = pb_vget(c, 4);
                if sent < size {
                    if now >= pb_vget(c, 6) { pnet_close(c); }
                    else {
                        let n = syscall(44, fd, c + 16384 + sent, size - sent, 16384, 0, 0);
                        if n > 0 { pb_vset(c, 4, sent + n); }
                        else if n != -11 && n != -4 { pnet_close(c); }
                    }
                }
                if load64(c) >= 0 && pb_vget(c, 4) == pb_vget(c, 3) {
                    pb_vset(c, 3, 0); pb_vset(c, 4, 0);
                    if pb_vget(c, 1) == 3 { syscall(48, fd, 1, 0, 0, 0, 0); pb_vset(c, 1, 4); pb_vset(c, 5, now + 250); }
                    if pb_vget(c, 15) && !pb_vget(c, 13) && pb_vget(c, 1) != 1 { pnet_close(c); }
                }
                if load64(c) >= 0 && pb_vget(c, 1) == 4 {
                    let n = syscall(0, fd, c + 512, 4096, 0, 0, 0);
                    if n == 0 || now >= pb_vget(c, 5) || (n < 0 && n != -11 && n != -4) { pnet_close(c); }
                }
            }
        }
        i = i + 1;
    }
    return 0;
}
fn pnet_dispatch_at(app, now, controller_now) {
    let i = 0;
    while i < 32 {
        let c = pn_clients + i * 65536;
        if load64(c) >= 0 {
            if pb_vget(c, 1) == 1 {
                let builder = pn_builder + 32; pl_builder(builder, pn_body, 65536);
                let status = pr_request(app, c + 128, c + 160, c + 512 + pb_vget(c, 10), pb_vget(c, 9), builder, controller_now);
                if load64(builder + 24) { pnet_error(c, 500, "response exceeds buffer", now); }
                else { pnet_reply(c, status, "application/json; charset=utf-8", pn_body, load64(builder + 8), now); }
            }
            else if pb_vget(c, 1) == 2 && pb_vget(c, 13) == 2 {
                let robot = load64(app); store64(robot + 4240, pb_vget(c, 7));
                let n = pr_wire(app, c + 13000, pb_vget(c, 14), pn_body, controller_now);
                if !pb_vget(c, 7) && load64(robot + 4240) { pb_vset(c, 8, (load64(robot + 4248) - 1) & 0xffffffff); }
                pb_vset(c, 7, load64(robot + 4240)); if n > 0 { pnet_ws_send(c, 2, pn_body, n, now); } pb_vset(c, 13, 0);
                pnet_websocket(c, now);
            }
        }
        i = i + 1;
    }
    return 0;
}
fn pnet_dispatch(app, now) { return pnet_dispatch_at(app, now, now); }
fn pnet_telemetry(app, now) {
    let robot = load64(app); let seq = load64(robot + 4248); let n = 0; let i = 0;
    while i < 32 {
        let c = pn_clients + i * 65536;
        if load64(c) >= 0 && pb_vget(c, 1) == 2 && pb_vget(c, 7) && pb_vget(c, 8) != seq {
            if !n { n = pb_arm_state_frame(robot, pn_body, 512); }
            pnet_ws_send(c, 2, pn_body, n, now); pb_vset(c, 8, seq);
        }
        i = i + 1;
    }
    return 0;
}
