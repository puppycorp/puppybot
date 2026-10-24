// One resident detector worker. Camera requests never block the Gym event loop.
global gv_manifest = 0;
global gv_binary = 0;
global gv_kernel = 0;
global gv_backend = 0;
global gv_device = 0;
global gv_job = 0;
global gv_buffer = 0;
global gv_state = 0;
global gv_client = 0;
global gv_client_fd = -1;
global gv_deadline = 0;
global gv_sequence = 0;
global gv_log = 0;
global gv_name = 0;
fn gv_init() {
    gv_job = alloc(32); gv_buffer = alloc(65536); gv_state = "idle"; gv_name = "No model prepared"; pn_binary_path = "/api/gym/vision/frame";
    let n = pl_read_file(gv_manifest, gv_buffer, 65535); if n > 0 { let model = pj_parse(gv_buffer, n); let name = pj_string_field(model, "id"); if !pj_error { let size = pl_size(name); gv_name = alloc(size + 1); pb_copy(gv_name, name, size + 1); } } return 0;
}
fn gv_authorized(c) {
    let data = c + 512; let end = pb_vget(c, 10); let host = ph_header(data, end, "host"); if !host || ph_duplicates { return 0; }
    let h = m_slice(host, ph_value_size); if !m_eq(h, m_cat("localhost:", m_int(pn_port))) && !m_eq(h, m_cat("127.0.0.1:", m_int(pn_port))) { return 0; }
    let origin = ph_header(data, end, "origin"); if origin && (ph_duplicates || !m_eq(m_slice(origin, ph_value_size), m_cat("http://", h))) { return 0; }
    let token = ph_header(data, end, "x-monolith-token"); return token && !ph_duplicates && m_eq(m_slice(token, ph_value_size), sv_token);
}
fn gv_start() {
    if load64(gv_job) > 0 { return 1; }
    if syscall(21, gv_manifest, 4, 0, 0, 0, 0) || syscall(21, gv_binary, 1, 0, 0, 0, 0) || (!pl_equal(gv_backend, "cpu") && syscall(21, gv_kernel, 4, 0, 0, 0, 0)) { gv_state = "unavailable"; return 0; }
    let b = gm_work + 12288; gv_log = alloc(4096); pl_builder(b, gv_log, 4096); pl_text(b, gm_root); pl_text(b, "/vision-"); pl_uint(b, syscall(39, 0, 0, 0, 0, 0, 0)); pl_char(b, 45); pl_uint(b, gv_sequence); pl_text(b, ".log"); gv_sequence = gv_sequence + 1;
    let args = alloc(96); store64(args, gv_binary); store64(args + 8, "worker"); store64(args + 16, "--model"); store64(args + 24, gv_manifest); store64(args + 32, "--kernel"); store64(args + 40, gv_kernel); store64(args + 48, "--backend"); store64(args + 56, gv_backend); store64(args + 64, "--device"); store64(args + 72, gv_device); store64(args + 80, 0);
    if !gx_spawn(gv_binary, args, gv_log, gv_job) { gv_state = "error"; return 0; } gv_state = "loading"; gv_deadline = pl_now() + 15000; return 1;
}
fn gv_finish_response(status, bytes, size, now) {
    if gv_client && load64(gv_client) == gv_client_fd && pb_vget(gv_client, 1) == 5 { pnet_reply(gv_client, status, "application/json; charset=utf-8", bytes, size, now); }
    gv_client = 0; gv_client_fd = -1; return 0;
}
fn gv_poll(now) {
    let pid = load64(gv_job); if pid <= 0 { return 0; }
    let fd = load64(gv_job + 8); let n = syscall(45, fd, gv_buffer, 65536, 32, 0, 0);
    if n > 0 && n <= 30000 {
        if pl_equal(gv_state, "loading") && n == 14 && pl_case_equal(gv_buffer, n, "{\"ready\":true}") { gv_state = "ready"; gv_deadline = 0; }
        else if pl_equal(gv_state, "busy") { gv_finish_response(200, gv_buffer, n, now); gv_state = "ready"; gv_deadline = 0; }
    }
    let status = gx_reap(pid, 0);
    if !n || status != -2 || (gv_deadline && now >= gv_deadline) {
        if status == -2 { syscall(62, pid, 9, 0, 0, 0, 0); gx_reap(pid, 1000); }
        syscall(3, fd, 0, 0, 0, 0, 0); store64(gv_job, 0); gv_state = "error"; gv_deadline = 0;
        let message = "{\"error\":\"Detector stopped; inspect the vision worker log\"}"; gv_finish_response(503, message, pl_size(message), now);
    }
    return 0;
}
fn gv_request(c, now) {
    let path = c + 160; if !pl_starts(path, "/api/gym/vision") { return 0; }
    if !gv_authorized(c) { pnet_error(c, 403, "Vision request token/origin rejected", now); return 1; }
    if pl_equal(path, "/api/gym/vision") && pl_equal(c + 128, "GET") {
        let b = pn_builder + 32; pl_builder(b, pn_body, 65536); pl_text(b, "{\"state\":"); pj_text(b, gv_state); pl_text(b, ",\"model\":"); pj_text(b, gv_name); pl_text(b, ",\"configured\":"); pj_bool_text(b, !syscall(21, gv_manifest, 4, 0, 0, 0, 0)); pl_text(b, "}"); pnet_reply(c, 200, "application/json", pn_body, load64(b + 8), now); return 1;
    }
    if !pl_equal(c + 128, "POST") { pnet_error(c, 405, "Vision requires POST", now); return 1; }
    if pl_equal(path, "/api/gym/vision/start") {
        if !gv_start() { pnet_error(c, 503, "Prepare the model and shared Pup kernels before starting Live", now); return 1; }
        pnet_reply(c, 200, "application/json", "{\"ok\":true}", 11, now); return 1;
    }
    if pl_equal(path, "/api/gym/vision/frame") {
        if !pl_equal(gv_state, "ready") { pnet_error(c, 409, "Detector is loading or busy", now); return 1; }
        let size = pb_vget(c, 9); let body = c + 512 + pb_vget(c, 10); let type = ph_header(c + 512, pb_vget(c, 10), "content-type");
        if !type || ph_duplicates || !pl_case_equal(type, ph_value_size, "image/jpeg") || size < 8 || size > 48000 || load8(body) != 255 || load8(body + 1) != 216 { pnet_error(c, 415, "Expected a JPEG frame of at most 48000 bytes", now); return 1; }
        store64(gv_buffer, gv_sequence); gv_sequence = gv_sequence + 1; store64(gv_buffer + 8, now); pb_copy(gv_buffer + 16, body, size);
        let n = syscall(44, load64(gv_job + 8), gv_buffer, size + 16, 16384, 0, 0);
        if n != size + 16 { pnet_error(c, 503, "Detector transport is unavailable", now); return 1; }
        gv_state = "busy"; gv_client = c; gv_client_fd = load64(c); gv_deadline = now + 10000; pb_vset(c, 1, 5); return 1;
    }
    pnet_error(c, 404, "Unknown vision endpoint", now); return 1;
}
fn gv_close() { if load64(gv_job) > 0 { gx_finish(load64(gv_job), load64(gv_job + 8)); store64(gv_job, 0); } return 0; }
