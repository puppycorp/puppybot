// Transfer completed UI requests from the shared bounded listener to Monolith.
// Rendering, form validation, action tokens, dispatch, SSE and patches are upstream.
import "monolith";

fn gm_monolith_init(port) {
    mono_name = "PuppyBotGym"; sv_port = port; sv_revision = 0; sv_snapshot = 0;
    let random = alloc(16); let i = 0;
    while i < 16 { let n = syscall(318, random + i, 16 - i, 0, 0, 0, 0); if n > 0 { i = i + n; } else if n != -4 { return 0; } }
    sv_token = alloc(33); let hex = "0123456789abcdef"; i = 0;
    while i < 16 { let byte = load8(random + i); store8(sv_token + i * 2, load8(hex + (byte >> 4))); store8(sv_token + i * 2 + 1, load8(hex + (byte & 15))); i = i + 1; } store8(sv_token + 32, 0);
    sv_slots = alloc(4096); pb_zero(sv_slots, 4096); i = 0; while i < 64 { store64(sv_slots + i * 64, -1); i = i + 1; }
    sv_refresh(); return 1;
}
fn gm_monolith_route(path) {
    return pl_equal(path, "/") || pl_equal(path, "/live") || pl_equal(path, "/cases") || pl_equal(path, "/client.js") || pl_equal(path, "/style.css") || pl_equal(path, "/events") || pl_equal(path, "/action");
}
fn gm_page_reply(fd) {
    let body = sv_html(); let b = m_buffer();
    m_text(b, "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: "); m_text(b, m_int(m_len(body)));
    m_text(b, "\r\nConnection: close\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nContent-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'\r\n\r\n");
    if !m_eq(sv_method, "HEAD") { m_text(b, body); } return m_send(fd, m_data(b), load64(b + 8));
}
fn gm_monolith_request(c) {
    let slot = 0; let i = 0;
    while i < 64 && !slot { let candidate = sv_slots + i * 64; if load64(candidate) < 0 { slot = candidate; } i = i + 1; }
    if !slot { return 0; }
    let bytes = alloc(16384); if bytes <= 0 { return 0; }
    let size = pb_vget(c, 2); pb_copy(bytes, c + 512, size); pb_zero(slot, 64);
    store64(slot, load64(c)); store64(c, -1); store64(slot + 8, bytes); store64(slot + 16, size); store64(slot + 32, pb_vget(c, 10));
    let code = sv_parse(slot);
    if code == 200 {
        if (m_eq(sv_method, "GET") || m_eq(sv_method, "HEAD")) && (m_eq(sv_path, "/") || m_eq(sv_path, "/live") || m_eq(sv_path, "/cases")) { gm_page_reply(load64(slot)); sv_close(slot); }
        else if m_eq(sv_method, "GET") && m_eq(sv_path, "/client.js") { sv_reply(load64(slot), 200, "text/javascript; charset=utf-8", m_cat(mono_client_js(), gm_camera_js()), ""); sv_close(slot); }
        else { sv_dispatch(slot); }
    }
    else { if !code { code = 400; } sv_reply(load64(slot), code, "text/plain; charset=utf-8", "Invalid Monolith request\n", ""); sv_close(slot); }
    return 1;
}
fn gm_monolith_poll() {
    let i = 0; let scratch = m_take(32);
    while i < 64 {
        let slot = sv_slots + i * 64;
        if load64(slot) >= 0 && load64(slot + 48) == 1 {
            let n = syscall(0, load64(slot), scratch, 32, 0, 0, 0);
            if n >= 0 || (n != -4 && n != -11) { sv_close(slot); }
        }
        i = i + 1;
    }
    return 0;
}
fn gm_monolith_refresh() { let patch = sv_refresh(); sv_revision = sv_revision + 1; sv_broadcast(patch); return 0; }
fn gm_monolith_heartbeat() {
    let i = 0; while i < 64 { let slot = sv_slots + i * 64; if load64(slot) >= 0 && load64(slot + 48) == 1 { if !m_send_for(load64(slot), ": keepalive\n\n", 13, 25) { sv_close(slot); } } i = i + 1; } return 0;
}
fn gm_monolith_close() { let i = 0; while i < 64 { sv_close(sv_slots + i * 64); i = i + 1; } if sv_snapshot { m_free_state(sv_snapshot); sv_snapshot = 0; } return 0; }
