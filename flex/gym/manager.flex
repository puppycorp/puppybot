// Gym owns experiment lifecycle and artifacts. It exposes no robot controls.
import "runner.flex";
import "cases.flex";
import "../runtime/server.flex";
import "../../build/flex/gym-flexdb.flex";
import "monolith.flex";
import "vision.flex";
import "artifacts.flex";

global gm_db = 0;
global gm_runs = 0;
global gm_root = 0;
global gm_firmware = 0;
global gm_binary = 0;
global gm_jobs = 0;
global gm_work = 0;
global gm_lock = -1;
global gm_simulator = 0;

fn gm_values(name, seed, path, state) {
    let v = flexdb_values(gm_db); flexdb_add(gm_db, v, flexdb_text(gm_db, name)); flexdb_add(gm_db, v, flexdb_int(gm_db, seed));
    flexdb_add(gm_db, v, flexdb_text(gm_db, path)); flexdb_add(gm_db, v, flexdb_text(gm_db, state)); return v;
}
fn gm_state(row, state) {
    let name = flexdb_word(flexdb_cell(row, 0)); let seed = flexdb_word(flexdb_cell(row, 1)); let path = flexdb_word(flexdb_cell(row, 2)); let id = load64(row);
    if !flexdb_begin(gm_db) { return 0; }
    if !flexdb_update(gm_runs, id, gm_values(name, seed, path, state)) { flexdb_rollback(gm_db); return 0; } return flexdb_commit(gm_db);
}
fn gm_row_json(b, row) {
    pl_text(b, "{\"id\":"); pl_uint(b, load64(row)); pl_text(b, ",\"case\":"); pj_text(b, flexdb_word(flexdb_cell(row, 0)));
    pl_text(b, ",\"seed\":"); pl_uint(b, flexdb_word(flexdb_cell(row, 1))); pl_text(b, ",\"status\":"); pj_text(b, flexdb_word(flexdb_cell(row, 3)));
    pl_text(b, ",\"directory\":"); pj_text(b, flexdb_word(flexdb_cell(row, 2))); return pl_char(b, 125);
}
fn gm_load(row, leaf) {
    gr_path(gm_work, flexdb_word(flexdb_cell(row, 2)), leaf); let n = pl_read_file(gm_work, gm_work + 4096, 8192);
    if n < 0 { return 0; } return pj_parse(gm_work + 4096, n);
}
fn gm_terminal(row, fallback) {
    let root = gm_load(row, "result.json"); if !root { return fallback; }
    let state = pj_string_field(root, "status"); if pj_error || !state { return fallback; }
    if pl_equal(state, "passed") { return "passed"; } if pl_equal(state, "failed") { return "failed"; }
    if pl_equal(state, "cancelled") { return "cancelled"; } return "error";
}
fn gm_poll_jobs() {
    let i = 0;
    while i < 8 {
        let job = gm_jobs + i * 32; let pid = load64(job);
        if pid > 0 {
            let status = gx_reap(pid, 0);
            if status != -2 {
                let row = flexdb_get(gm_runs, load64(job + 8)); if row { if !gm_state(row, gm_terminal(row, "error")) { return 0; } }
                store64(job, 0);
            }
        }
        i = i + 1;
    }
    return 1;
}
fn gm_run_path(out, id, suffix) {
    let b = gm_work + 12288; pl_builder(b, out, 4096); pl_text(b, gm_root); pl_text(b, "/run-"); pl_uint(b, id); if suffix { pl_text(b, suffix); } return !load64(b + 24);
}
fn gm_start(name, seed) {
    let i = 0; let job = 0;
    while i < 8 && !job { let slot = gm_jobs + i * 32; if !load64(slot) { job = slot; } i = i + 1; }
    if !job { return -8; }
    // The table assigns monotonically increasing IDs. The folder is fixed here.
    let id = load64(gm_runs + 32); let path = gm_work + 16384; if !gm_run_path(path, id, 0) { return -1; }
    if !flexdb_begin(gm_db) { return -1; }
    if !flexdb_insert(gm_runs, gm_values(name, seed, path, "running")) || !flexdb_commit(gm_db) { flexdb_rollback(gm_db); return -1; }
    let log = gm_work + 20480; gm_run_path(log, id, ".log");
    let seed_text = gm_work + 24576; let b = gm_work + 12288; pl_builder(b, seed_text, 64); pl_uint(b, seed);
    let args = gm_work + 24832; store64(args, gm_binary); store64(args + 8, "worker"); store64(args + 16, "--output"); store64(args + 24, path);
    store64(args + 32, "--case"); store64(args + 40, name); store64(args + 48, "--seed"); store64(args + 56, seed_text);
    store64(args + 64, "--firmware"); store64(args + 72, gm_firmware);
    if gg_native_case(name) {
        store64(args + 80, 0); if gm_simulator { store64(args + 80, "--simulator"); store64(args + 88, gm_simulator); store64(args + 96, 0); }
    } else { store64(args + 80, "--realtime"); store64(args + 88, 0); }
    if !gx_spawn(gm_binary, args, log, job) { gm_state(flexdb_get(gm_runs, id), "error"); return -1; }
    syscall(3, load64(job + 8), 0, 0, 0, 0, 0); store64(job + 8, id); return id;
}
fn gm_control(row, action) {
    let state = flexdb_word(flexdb_cell(row, 3));
    if !pl_equal(state, "running") && !pl_equal(state, "paused") { return 0; }
    gr_path(gm_work, flexdb_word(flexdb_cell(row, 2)), "control");
    if pl_atomic_file(gm_work, action, pl_size(action)) { return 0; }
    if pl_equal(action, "pause") { return gm_state(row, "paused"); }
    if pl_equal(action, "resume") { return gm_state(row, "running"); } return 1;
}
fn gm_samples(row, b) {
    let stride = 1; let progress = gm_load(row, "progress.json");
    if progress {
        let step = pj_integer(progress, "step", 0, 10000000); let sampling = 1;
        if pj_get(progress, "sampleStride") { sampling = pj_integer(progress, "sampleStride", 1, 10000); }
        if !pj_error { stride = pb_max((step / sampling + 31) / 32, 1); }
    }
    gr_path(gm_work, flexdb_word(flexdb_cell(row, 2)), "observations.jsonl"); let fd = syscall(2, gm_work, 0x80000, 0, 0, 0, 0);
    pl_char(b, 91); if fd < 0 { return pl_char(b, 93); }
    let input = gm_work + 28672; let line = gm_work + 32768; let used = 0; let count = 0; let index = 0; let active = 1;
    while active && count < 32 && index < 1000001 {
        let n = syscall(0, fd, input, 4096, 0, 0, 0);
        if n > 0 {
            let i = 0;
            while i < n && count < 32 {
                let c = load8(input + i); i = i + 1;
                if c == 10 {
                    if index % stride == 0 {
                        let node = pj_parse(line, used); if node { if count { pl_char(b, 44); } pj_emit(b, node); count = count + 1; }
                    }
                    used = 0; index = index + 1;
                } else { if used < 4095 { store8(line + used, c); used = used + 1; } else { active = 0; } }
            }
        } else if n != -4 { active = 0; }
    }
    syscall(3, fd, 0, 0, 0, 0, 0); return pl_char(b, 93);
}
fn gm_request(method, path, body, size, b) {
    if pl_equal(method, "GET") && pl_equal(path, "/api/gym/cases") { gg_cases(b); return 200; }
    if pl_equal(path, "/api/gym/runs") {
        if pl_equal(method, "GET") {
            let q = flexdb_query(gm_db); let rows = flexdb_scan(q, gm_runs); let n = flexdb_count(rows); let i = pb_max(n - 50, 0); pl_char(b, 91);
            while i < n { if i > pb_max(n - 50, 0) { pl_char(b, 44); } gm_row_json(b, flexdb_at(rows, i)); i = i + 1; }
            flexdb_query_close(q); pl_char(b, 93); return 200;
        }
        if !pl_equal(method, "POST") { return 405; }
        let root = pj_parse(body, size); let name = pj_string_field(root, "case"); let seed = pj_integer(root, "seed", 0, 0xffffffff);
        if pj_error || !name || !gg_case_valid(name) { return 400; }
        let id = gm_start(name, seed); if id < 0 { if id == -8 { return 409; } return 500; }
        gm_row_json(b, flexdb_get(gm_runs, id)); return 200;
    }
    if pl_starts(path, "/api/gym/runs/") {
        let text = path + 14; let n = 0; while load8(text + n) >= 48 && load8(text + n) <= 57 { n = n + 1; }
        let id = pl_integer(text, n); if pl_bad_number || id < 1 { return 404; } let row = flexdb_get(gm_runs, id); if !row { return 404; }
        let tail = text + n;
        if pl_equal(method, "GET") && !load8(tail) {
            pl_text(b, "{\"run\":"); gm_row_json(b, row); pl_text(b, ",\"progress\":"); let root = gm_load(row, "progress.json"); if root { pj_emit(b, root); } else { pl_text(b, "null"); }
            pl_text(b, ",\"endpoint\":"); root = gm_load(row, "endpoint.json"); if root { pj_emit(b, root); } else { pl_text(b, "null"); } pl_char(b, 125); return 200;
        }
        if pl_equal(method, "GET") && pl_equal(tail, "/samples") { gm_samples(row, b); return 200; }
        if pl_equal(method, "POST") && (pl_equal(tail, "/pause") || pl_equal(tail, "/resume") || pl_equal(tail, "/stop")) {
            if !gm_control(row, tail + 1) { return 409; } pl_text(b, "{\"ok\":true}"); return 200;
        }
    }
    return 404;
}
fn gm_database(root) {
    gm_root = root; gm_work = alloc(40960); gm_jobs = alloc(256); let error = syscall(83, root, 448, 0, 0, 0, 0); if error && error != -17 { return 0; }
    gr_path(gm_work, root, ".lock"); gm_lock = syscall(2, gm_work, 0x80042, 384, 0, 0, 0);
    if gm_lock < 0 || syscall(73, gm_lock, 6, 0, 0, 0, 0) { return 0; }
    gr_path(gm_work, root, "gym.db"); gm_db = open_flexdb(gm_work); if !gm_db { return 0; } gm_runs = flexdb_table(gm_db, "runs");
    if !gm_runs {
        if !flexdb_begin(gm_db) { return 0; } let s = flexdb_schema(gm_db);
        flexdb_column(gm_db, s, "case", 2, 0); flexdb_column(gm_db, s, "seed", 1, 0); flexdb_column(gm_db, s, "path", 2, 0); flexdb_column(gm_db, s, "state", 2, 0);
        gm_runs = flexdb_create(gm_db, "runs", s); if !gm_runs || !flexdb_commit(gm_db) { return 0; }
    }
    // Persisted PIDs are never signalled. Only this process's live children count.
    let q = flexdb_query(gm_db); let rows = flexdb_scan(q, gm_runs); let i = 0;
    while i < flexdb_count(rows) {
        let row = flexdb_at(rows, i); let state = flexdb_word(flexdb_cell(row, 3));
        if pl_equal(state, "running") || pl_equal(state, "paused") { if !gm_state(row, gm_terminal(row, "interrupted")) { return 0; } } i = i + 1;
    }
    flexdb_query_close(q); return 1;
}
fn gm_serve(argc, argv) {
    let root = "build/flex/gym-runs"; let bind = "127.0.0.1:8090"; gm_firmware = "build/flex/puppybot-firmware-sim"; gm_binary = "/proc/self/exe";
    gv_manifest = "build/flex/vision/yolo26n/model.json"; gv_binary = "build/flex/puppybot-vision"; gv_kernel = "build/flex/pup-kernels"; gv_backend = "auto"; gv_device = "0";
    let i = 2;
    while i < argc {
        if i + 1 >= argc { return 2; } let arg = pb_vget(argv, i); let value = pb_vget(argv, i + 1);
        if pl_equal(arg, "--data") { root = value; } else if pl_equal(arg, "--bind") { bind = value; }
        else if pl_equal(arg, "--firmware") { gm_firmware = value; }
        else if pl_equal(arg, "--simulator") { gm_simulator = value; }
        else if pl_equal(arg, "--model") { gv_manifest = value; }
        else if pl_equal(arg, "--vision") { gv_binary = value; }
        else if pl_equal(arg, "--backend") { if !pl_equal(value, "auto") && !pl_equal(value, "cpu") && !pl_equal(value, "sass") && !pl_equal(value, "cuda") && !pl_equal(value, "hip") { return 2; } gv_backend = value; }
        else if pl_equal(arg, "--device") { let ordinal = pl_integer(value, pl_size(value)); if pl_bad_number || ordinal < 0 || ordinal > 15 { return 2; } gv_device = value; }
        else if pl_equal(arg, "--vision-kernel") { gv_kernel = value; } else { return 2; } i = i + 2;
    }
    if pl_size(root) > 3000 || app_init(root) { pl_print(2, "Cannot open Gym data directory/database, or another manager holds its lock.\n"); return 1; }
    let address = alloc(16); let colon = ph_find(bind, pl_size(bind), ":", 1); if colon < 1 { return 2; }
    let port = pl_integer(bind + colon + 1, pl_size(bind + colon + 1)); if pl_bad_number || port < 0 || port > 65535 || !pl_sockaddr(address, bind, colon, port) { return 2; }
    if pb_u32(address + 4) != 0x0100007f { pl_print(2, "Monolith Gym binds only to 127.0.0.1.\n"); return 2; }
    if pnet_init(address) < 0 { return 1; } gv_init(); ga_init(); if !gm_monolith_init(pn_port) { return 1; } let signal = pl_signals(); let data = alloc(128); let b = pn_builder + 32;
    pl_builder(b, pn_body, 65536); pl_text(b, "PuppyBotGym listening on port "); pl_uint(b, pn_port); pl_char(b, 10); pl_print(1, pn_body);
    let alive = 1; let mark = m_mark(); let last_check = pl_now(); let heartbeat = last_check;
    while alive {
        let now = pl_now(); pnet_io(now); ga_poll(now); gv_poll(now); if !gm_poll_jobs() { alive = 0; }
        gm_monolith_poll();
        if syscall(0, signal, data, 128, 0, 0, 0) > 0 { alive = 0; }
        i = 0;
        while i < 32 {
            let c = pn_clients + i * 65536;
            if load64(c) >= 0 && pb_vget(c, 1) == 2 { pnet_ws_close(c, 1008, now); }
            if load64(c) >= 0 && pb_vget(c, 1) == 1 {
                if ga_request(c, now) {}
                else if gv_request(c, now) {}
                else if gm_monolith_route(c + 160) { if !gm_monolith_request(c) { pnet_error(c, 503, "Monolith is busy", now); } }
                else {
                    pl_builder(b, pn_body, 65536); let status = gm_request(c + 128, c + 160, c + 512 + pb_vget(c, 10), pb_vget(c, 9), b);
                    if status != 200 { pnet_error(c, status, "Gym request rejected", now); }
                    else if load64(b + 24) || load64(b + 8) > 32000 { pnet_error(c, 500, "Gym response exceeds limit", now); }
                    else { pnet_reply(c, 200, "application/json; charset=utf-8", pn_body, load64(b + 8), now); }
                }
            }
            i = i + 1;
        }
        if now - last_check >= 200 { last_check = now; if app_tick() { gm_monolith_refresh(); } }
        if now - heartbeat >= 15000 { heartbeat = now; gm_monolith_heartbeat(); }
        m_reset(mark);
        syscall(7, 0, 0, 5, 0, 0, 0);
    }
    // Ask workers to stop and let them complete the firmware's zero-speed cycle.
    i = 0; while i < 8 { let job = gm_jobs + i * 32; if load64(job) > 0 { gm_control(flexdb_get(gm_runs, load64(job + 8)), "stop"); } i = i + 1; }
    let deadline = pl_now() + 3000; let remaining = 1;
    while remaining && pl_now() < deadline { gm_poll_jobs(); remaining = 0; i = 0; while i < 8 { if load64(gm_jobs + i * 32) { remaining = 1; } i = i + 1; } if remaining { syscall(7, 0, 0, 5, 0, 0, 0); } }
    i = 0; while i < 8 { let job = gm_jobs + i * 32; if load64(job) > 0 { syscall(62, load64(job), 9, 0, 0, 0, 0); gx_reap(load64(job), 1000); gm_state(flexdb_get(gm_runs, load64(job + 8)), "interrupted"); } i = i + 1; }
    i = 0; while i < 32 { ga_close(ga_jobs + i * 24); i = i + 1; }
    gv_close(); gm_monolith_close(); close_flexdb(gm_db); return 0;
}
