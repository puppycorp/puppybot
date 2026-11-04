// WebSocket client with absolute deadlines and signal-aware timed motion.
import "../host/http.flex";

global pcc_fd = -1;
global pcc_rx = 0;
global pcc_used = 0;
global pcc_tx = 0;
global pcc_message = 0;
global pcc_size = 0;
global pcc_opcode = 0;
global pcc_fragment = 0;
global pcc_fragment_size = 0;
global pcc_meta = 0;
global pcc_poll = 0;
global pcc_cancelled = 0;
global pcc_ignore_signal = 0;
global pcc_error = 0;

fn pcc_fail(message) { pcc_error = message; return 0; }
fn pcc_random(out, size) {
    let at = 0; while at < size { let n = syscall(318, out + at, size - at, 0, 0, 0, 0); if n > 0 { at = at + n; } else if n != -4 { return 0; } } return 1;
}
fn pcc_wait(events, deadline) {
    while 1 {
        let remaining = deadline - pl_now(); if remaining <= 0 { return pcc_fail("runtime operation timed out"); }
        store64(pcc_poll, (pcc_fd & 0xffffffff) | (events << 32)); let count = 1;
        if !pcc_ignore_signal { store64(pcc_poll + 8, (pl_signal & 0xffffffff) | (1 << 32)); count = 2; }
        let n = syscall(7, pcc_poll, count, remaining, 0, 0, 0);
        if n < 0 && n != -4 { return pcc_fail("runtime socket poll failed"); }
        if n > 0 {
            if count == 2 && ((load64(pcc_poll + 8) >> 48) & 65535) {
                let signal = pcc_poll + 128;
                if syscall(0, pl_signal, signal, 128, 0, 0, 0) > 0 { pcc_cancelled = pb_u32(signal); return pcc_fail("interrupted"); }
            }
            if (load64(pcc_poll) >> 48) & 65535 { return 1; }
        }
    }
    return 0;
}
fn pcc_write(data, size, deadline) {
    let at = 0;
    while at < size {
        let n = syscall(44, pcc_fd, data + at, size - at, 16384, 0, 0);
        if n > 0 { at = at + n; }
        else if n == -11 { if !pcc_wait(4, deadline) { return 0; } }
        else if n != -4 { return pcc_fail("runtime socket write failed"); }
    }
    return 1;
}
fn pcc_read(deadline) {
    if pcc_used >= 12288 { return pcc_fail("runtime response exceeds input limit"); }
    while 1 {
        let n = syscall(0, pcc_fd, pcc_rx + pcc_used, 12288 - pcc_used, 0, 0, 0);
        if n > 0 { pcc_used = pcc_used + n; return 1; }
        if !n { return pcc_fail("runtime websocket closed"); }
        if n == -11 { if !pcc_wait(1, deadline) { return 0; } }
        else if n != -4 { return pcc_fail("runtime socket read failed"); }
    }
    return 0;
}
fn pcc_consume(n) { pb_copy(pcc_rx, pcc_rx + n, pcc_used - n); pcc_used = pcc_used - n; return 0; }
fn pcc_send(opcode, data, size, deadline) {
    let key = pcc_meta + 64; if !pcc_random(key, 4) { return pcc_fail("cannot obtain WebSocket mask randomness"); }
    let n = pw_frame(pcc_tx, 4096, opcode, data, size, 1, pb_u32(key));
    if n < 0 { return pcc_fail("outgoing frame exceeds limit"); } return pcc_write(pcc_tx, n, deadline);
}
fn pcc_url(url, address, host, target) {
    if !pl_starts(url, "ws://") { return pcc_fail("URL must use ws://"); }
    let end = 5; while load8(url + end) && load8(url + end) != 47 { end = end + 1; }
    let size = end - 5; if size < 1 || size > 255 { return pcc_fail("invalid WebSocket host"); }
    let i = 5; while i < end { let c = load8(url + i); if c <= 32 || c >= 127 || c == 64 || c == 35 || c == 63 { return pcc_fail("invalid WebSocket authority"); } i = i + 1; }
    pb_copy(host, url + 5, size); store8(host + size, 0);
    let colon = ph_find(url + 5, size, ":", 1); let port = 80; let host_size = size;
    if colon >= 0 { host_size = colon; port = pl_integer(url + 6 + colon, size - colon - 1); if pl_bad_number || port < 1 || port > 65535 { return pcc_fail("invalid WebSocket port"); } }
    if !pl_resolve_address(address, url + 5, host_size, port) { return pcc_fail("cannot resolve IPv4 WebSocket host"); }
    if !load8(url + end) { pb_copy(target, "/", 2); }
    else {
        let n = pl_size(url + end); if n > 255 { return pcc_fail("WebSocket path exceeds 255 bytes"); }
        i = 0; while i < n { let c = load8(url + end + i); if c <= 32 || c >= 127 || c == 35 { return pcc_fail("invalid WebSocket path"); } i = i + 1; }
        pb_copy(target, url + end, n + 1);
    }
    return 1;
}
fn pcc_connect(url, timeout) {
    pcc_error = 0; pcc_cancelled = 0; pcc_ignore_signal = 0; pcc_used = 0; pcc_fragment = 0; pcc_fragment_size = 0;
    pcc_rx = alloc(12288); pcc_tx = alloc(4096); pcc_message = alloc(2048); pcc_meta = alloc(512); pcc_poll = alloc(512);
    let work = alloc(4096); let builder = alloc(32); let host = work; let target = work + 256; let address = work + 512;
    let random = work + 544; let key = work + 576; let accept = work + 608;
    if pcc_rx <= 0 || pcc_tx <= 0 || pcc_message <= 0 || pcc_meta <= 0 || pcc_poll <= 0 || work <= 0 || builder <= 0 { return pcc_fail("cannot allocate client buffers"); }
    if pl_signals() < 0 || !pcc_url(url, address, host, target) { return 0; }
    let deadline = pl_now() + timeout; pcc_fd = pl_connect(address, deadline); if pcc_fd < 0 { return pcc_fail("cannot connect to runtime"); }
    if !pcc_random(random, 16) { return pcc_fail("cannot obtain handshake randomness"); }
    pw_base64(key, random, 16); pw_accept(accept, key, 24, work + 1024);
    pl_builder(builder, pcc_tx, 4096); pl_text(builder, "GET "); pl_text(builder, target); pl_text(builder, " HTTP/1.1\r\nHost: "); pl_text(builder, host);
    pl_text(builder, "\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: "); pl_text(builder, key); pl_text(builder, "\r\n\r\n");
    if !pcc_write(pcc_tx, load64(builder + 8), deadline) { return 0; }
    let end = ph_find(pcc_rx, pcc_used, "\r\n\r\n", 4);
    while end < 0 { if !pcc_read(deadline) { return 0; } end = ph_find(pcc_rx, pcc_used, "\r\n\r\n", 4); }
    end = end + 4;
    if end < 17 || !pl_starts(pcc_rx, "HTTP/1.1 101 ") || !ph_headers_valid(pcc_rx, end) { return pcc_fail("runtime rejected WebSocket upgrade"); }
    let header = ph_header(pcc_rx, end, "sec-websocket-accept");
    if !header || ph_duplicates || ph_value_size != 28 || !pl_starts(header, accept) { return pcc_fail("invalid runtime WebSocket handshake digest"); }
    header = ph_header(pcc_rx, end, "upgrade"); if !header || ph_duplicates || !pl_case_equal(header, ph_value_size, "websocket") { return pcc_fail("invalid runtime Upgrade header"); }
    header = ph_header(pcc_rx, end, "connection"); if !header || !ph_has_token(header, ph_value_size, "upgrade") { return pcc_fail("invalid runtime Connection header"); }
    pcc_consume(end); return 1;
}
fn pcc_receive(deadline) {
    while 1 {
        let n = pw_parse(pcc_rx, pcc_used, 0, pcc_meta);
        if n < 0 { return pcc_fail("invalid runtime WebSocket frame"); }
        if !n { if !pcc_read(deadline) { return 0; } }
        else {
            let opcode = load64(pcc_meta); let fin = load64(pcc_meta + 8); let data = pcc_rx + load64(pcc_meta + 16); let size = load64(pcc_meta + 24);
            if opcode >= 8 {
                if opcode == 8 { return pcc_fail("runtime closed WebSocket connection"); }
                if opcode == 9 && !pcc_send(10, data, size, deadline) { return 0; }
            } else {
                if (opcode == 0 && !pcc_fragment) || (opcode != 0 && pcc_fragment) { return pcc_fail("invalid runtime message fragmentation"); }
                if opcode { pcc_fragment = opcode; pcc_fragment_size = 0; }
                if size > 2048 - pcc_fragment_size { return pcc_fail("runtime message exceeds 2048 bytes"); }
                pb_copy(pcc_message + pcc_fragment_size, data, size); pcc_fragment_size = pcc_fragment_size + size;
                if fin {
                    pcc_opcode = pcc_fragment; pcc_size = pcc_fragment_size; pcc_fragment = 0; pcc_fragment_size = 0;
                    if pcc_opcode == 1 && !ph_utf8(pcc_message, pcc_size) { return pcc_fail("invalid runtime text UTF-8"); }
                    pcc_consume(n); return 1;
                }
            }
            pcc_consume(n);
        }
    }
    return 0;
}
fn pcc_protocol(command, body, size, scratch, timeout) {
    store8(scratch, 1); store8(scratch + 1, command); pb_put16(scratch + 2, size); pb_copy(scratch + 4, body, size);
    return pcc_send(2, scratch, size + 4, pl_now() + timeout);
}
fn pcc_response(message, timeout) {
    let deadline = pl_now() + timeout;
    while pcc_receive(deadline) {
        if pcc_opcode == 2 && pcc_size >= 3 && pb_u16(pcc_message) == 1 && load8(pcc_message + 2) == message { return 1; }
    }
    return 0;
}
fn pcc_barrier(scratch, timeout) { if !pcc_protocol(1, scratch, 0, scratch + 128, timeout) { return 0; } return pcc_response(1, timeout); }
fn pcc_delay(duration) {
    let deadline = pl_now() + duration;
    while pl_now() < deadline {
        store64(pcc_poll, (pl_signal & 0xffffffff) | (1 << 32));
        let n = syscall(7, pcc_poll, 1, pb_max(deadline - pl_now(), 0), 0, 0, 0);
        if n > 0 {
            let data = pcc_poll + 128; if syscall(0, pl_signal, data, 128, 0, 0, 0) > 0 { pcc_cancelled = pb_u32(data); return 0; }
        } else if n < 0 && n != -4 { return 0; }
    }
    return 1;
}
fn pcc_close() {
    if pcc_fd >= 0 { syscall(48, pcc_fd, 2, 0, 0, 0, 0); syscall(3, pcc_fd, 0, 0, 0, 0, 0); pcc_fd = -1; } return 0;
}
