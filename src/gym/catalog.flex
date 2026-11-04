// Read-only, incremental index of visual-control recordings outside Gym.
// Each path is discovered beneath one of two fixed roots without following links.
import "../host/json.flex";

global gc_roots = 0;
global gc_frames = 0;
global gc_records = 0;
global gc_count = 0;
global gc_depth = 0;
global gc_source = 0;
global gc_done = 0;
global gc_truncated = 0;
global gc_buffer = 0;
global gc_how = 0;
global gc_sim_path = 0;
global gc_dataset_path = 0;
global gc_sim_label = 0;
global gc_dataset_label = 0;

fn gc_open(root, path, flags) {
    store64(gc_how, flags); store64(gc_how + 8, 0); store64(gc_how + 16, 12);
    return syscall(437, root, path, gc_how, 24, 0, 0);
}
fn gc_regular(fd, name) {
    let file = syscall(257, fd, name, 0xa0800, 0, 0, 0); if file < 0 { return -1; }
    let stat = gc_buffer + 16384; if syscall(5, file, stat, 0, 0, 0, 0) || (pb_u32(stat + 24) & 0xf000) != 0x8000 { syscall(3, file, 0, 0, 0, 0, 0); return -1; }
    return file;
}
fn gc_exists(fd, name) { let f = gc_regular(fd, name); if f < 0 { return 0; } syscall(3, f, 0, 0, 0, 0, 0); return 1; }
fn gc_read(fd, name) {
    let f = gc_regular(fd, name); if f < 0 { return 0; } let size = 0; let active = 1;
    while active && size < 8192 { let n = syscall(0, f, gc_buffer + size, 8192 - size, 0, 0, 0); if n > 0 { size = size + n; } else if n != -4 { active = 0; } }
    syscall(3, f, 0, 0, 0, 0, 0); if active || !size { return 0; } return pj_parse(gc_buffer, size);
}
fn gc_hash(source, path) {
    let a = 2166136261 + source; let b = 5381 + source; let i = 0;
    while load8(path + i) { let c = load8(path + i); a = ((a ^ c) * 16777619) & 0xffffffff; b = ((b * 33) ^ c) & 0x1fffff; i = i + 1; }
    return (b << 32) | a;
}
fn gc_add(path) {
    if gc_count >= 30000 { gc_truncated = 1; return 0; }
    let id = gc_hash(gc_source, path); let i = 0;
    while i < gc_count { if load64(gc_records + i * 24) == id { let existing = gc_records + i * 24; if load64(existing + 8) != gc_source || !pl_equal(load64(existing + 16), path) { gc_truncated = 1; } return 0; } i = i + 1; }
    let size = pl_size(path); let copy = alloc(size + 1); pb_copy(copy, path, size + 1); let row = gc_records + gc_count * 24;
    store64(row, id); store64(row + 8, gc_source); store64(row + 16, copy); gc_count = gc_count + 1; return 0;
}
fn gc_push(fd, path) {
    if fd < 0 { gc_truncated = 1; gc_source = gc_source + 1; return 0; }
    if gc_depth >= 16 || pl_size(path) >= 1024 { syscall(3, fd, 0, 0, 0, 0, 0); gc_truncated = 1; return 0; }
    let frame = gc_frames + gc_depth * 10272; pb_zero(frame, 32); store64(frame, fd); pb_copy(frame + 32, path, pl_size(path) + 1); gc_depth = gc_depth + 1;
    if gc_exists(fd, "initial.json") && gc_exists(fd, "decisions.jsonl") { gc_add(path); syscall(3, fd, 0, 0, 0, 0, 0); gc_depth = gc_depth - 1; }
    else if gc_exists(fd, "mission.mp4") || (gc_exists(fd, "result.json") && (gc_exists(fd, "trace.jsonl") || gc_exists(fd, "observations.jsonl"))) { gc_add(path); }
    return 0;
}
fn gc_init() {
    gc_sim_label = "build/flex/sim"; gc_dataset_label = "datasets/visual-control";
    gc_roots = alloc(16); gc_frames = alloc(164352); gc_records = alloc(720000); gc_buffer = alloc(16640); gc_how = alloc(24);
    let path = gc_buffer; let b = gc_buffer + 16512; pl_builder(b, path, 4096); pl_text(b, gg_project_root()); pl_text(b, "/build/flex/sim");
    if gc_sim_path { gc_sim_label = gc_sim_path; } else { gc_sim_path = path; }
    store64(gc_roots, syscall(2, gc_sim_path, 0xb0000, 0, 0, 0, 0)); pl_builder(b, path, 4096); pl_text(b, gg_project_root()); pl_text(b, "/datasets/visual-control");
    if gc_dataset_path { gc_dataset_label = gc_dataset_path; } else { gc_dataset_path = path; }
    store64(gc_roots + 8, syscall(2, gc_dataset_path, 0xb0000, 0, 0, 0, 0)); return 0;
}
fn gc_poll() {
    let budget = 80;
    while budget > 0 && !gc_done {
        if !gc_depth {
            if gc_source >= 2 { gc_done = 1; }
            else { let root = load64(gc_roots + gc_source * 8); if root < 0 { gc_source = gc_source + 1; } else { syscall(8, root, 0, 0, 0, 0, 0); gc_push(syscall(32, root, 0, 0, 0, 0, 0), ""); } }
        } else {
            let frame = gc_frames + (gc_depth - 1) * 10272; let at = load64(frame + 8); let used = load64(frame + 16);
            if at >= used { used = syscall(217, load64(frame), frame + 1056, 9216, 0, 0, 0); at = 0; store64(frame + 8, 0); store64(frame + 16, used); }
            if used <= 0 { syscall(3, load64(frame), 0, 0, 0, 0, 0); gc_depth = gc_depth - 1; if !gc_depth { gc_source = gc_source + 1; } }
            else {
                let entry = frame + 1056 + at; let length = pb_u16(entry + 16); if length < 20 || at + length > used { store64(frame + 8, used); }
                else {
                    store64(frame + 8, at + length); let name = entry + 19; budget = budget - 1;
                    if load8(entry + 18) == 4 && !pl_equal(name, ".") && !pl_equal(name, "..") && !pl_equal(name, "sensor") && !pl_equal(name, "sensors") && !pl_equal(name, "scene") && !pl_equal(name, "source-snapshot") && !pl_equal(name, "frames") {
                        let size = pl_size(frame + 32); let ns = pl_size(name);
                        if size + ns + 2 < 1024 {
                            let path = gc_buffer + 8192; let b = gc_buffer + 16512; pl_builder(b, path, 4096); pl_text(b, frame + 32); if size { pl_char(b, 47); } pl_text(b, name);
                            let fd = syscall(257, load64(frame), name, 0xb0000, 0, 0, 0); if fd >= 0 { gc_push(fd, path); }
                        } else { gc_truncated = 1; }
                    }
                }
            }
        }
    }
    return 0;
}
fn gc_find(id) { let i = 0; while i < gc_count { let row = gc_records + i * 24; if load64(row) == id { return row; } i = i + 1; } return 0; }
fn gc_directory(row) { let root = load64(gc_roots + load64(row + 8) * 8); if root < 0 { return -1; } return gc_open(root, load64(row + 16), 0xb0000); }
fn gc_artifact(id, leaf) {
    let row = gc_find(id); if !row { return -1; } let fd = gc_directory(row); if fd < 0 { return -1; }
    let file = gc_regular(fd, leaf); syscall(3, fd, 0, 0, 0, 0, 0); return file;
}
fn gc_emit_field(b, root, field) { let value = pj_get(root, field); if value { pj_emit(b, value); } else { pl_text(b, "null"); } return 0; }
fn gc_emit(b, row) {
    pl_text(b, "{\"id\":"); pl_uint(b, load64(row)); pl_text(b, ",\"source\":");
    if load64(row + 8) { pj_text(b, gc_dataset_label); } else { pj_text(b, gc_sim_label); }
    pl_text(b, ",\"path\":"); pj_text(b, load64(row + 16)); let fd = gc_directory(row);
    pl_text(b, ",\"teacherAssisted\":"); if fd >= 0 && gc_exists(fd, "supervision.json") { pl_text(b, "true"); } else { pl_text(b, "false"); }
    pl_text(b, ",\"video\":"); if fd >= 0 && gc_exists(fd, "mission.mp4") { pl_text(b, "true"); } else { pl_text(b, "false"); }
    pl_text(b, ",\"image\":"); if fd >= 0 && gc_exists(fd, "outcome.png") { pl_text(b, "true"); } else { pl_text(b, "false"); }
    pl_text(b, ",\"caseId\":"); let scene = -1; if fd >= 0 { scene = syscall(257, fd, "scene", 0xb0000, 0, 0, 0); }
    let case_node = 0; if scene >= 0 { case_node = gc_read(scene, "case.json"); syscall(3, scene, 0, 0, 0, 0, 0); }
    if case_node { gc_emit_field(b, case_node, "id"); } else { pl_text(b, "null"); }
    let result = 0; if fd >= 0 { result = gc_read(fd, "result.json"); syscall(3, fd, 0, 0, 0, 0, 0); }
    pl_text(b, ",\"result\":"); if result { pl_text(b, "{"); pl_text(b, "\"seed\":"); gc_emit_field(b, result, "seed"); pl_text(b, ",\"status\":"); gc_emit_field(b, result, "status"); pl_text(b, ",\"success\":"); gc_emit_field(b, result, "success"); pl_text(b, ",\"found\":"); gc_emit_field(b, result, "found"); pl_text(b, ",\"steps\":"); gc_emit_field(b, result, "steps"); pl_text(b, ",\"simulationSeconds\":"); gc_emit_field(b, result, "simulationSeconds"); pl_text(b, ",\"controller\":"); gc_emit_field(b, result, "controller"); pl_text(b, "}"); } else { pl_text(b, "null"); }
    return pl_char(b, 125);
}
fn gc_request(path, b) {
    let prefix = "/api/gym/catalog/"; if !pl_starts(path, prefix) { return 404; } let tail = path + pl_size(prefix); let gym = 0;
    if pl_equal(tail, "refresh") { if gc_done { gc_source = 0; gc_done = 0; gc_truncated = 0; } pl_text(b, "{\"ok\":true}"); return 200; }
    if pl_starts(tail, "gym/") { gym = 1; tail = tail + 4; } else if pl_starts(tail, "history/") { tail = tail + 8; } else { return 404; }
    let offset = pl_integer(tail, pl_size(tail)); if pl_bad_number || offset < 0 || offset > 1000000 { return 400; }
    let count = gc_count; let q = 0; let rows = 0;
    if gym { q = flexdb_query(gm_db); rows = flexdb_scan(q, gm_runs); count = flexdb_count(rows); }
    let end = pb_min(offset + 20, count); pl_text(b, "{\"total\":"); pl_uint(b, count); pl_text(b, ",\"done\":"); if gym || gc_done { pl_text(b, "true"); } else { pl_text(b, "false"); }
    pl_text(b, ",\"truncated\":"); if !gym && gc_truncated { pl_text(b, "true"); } else { pl_text(b, "false"); } pl_text(b, ",\"items\":[");
    let i = offset; while i < end { if i > offset { pl_char(b, 44); } if gym { gm_row_json(b, flexdb_at(rows, count - 1 - i)); } else { gc_emit(b, gc_records + i * 24); } i = i + 1; }
    if q { flexdb_query_close(q); } pl_text(b, "]}"); return 200;
}
fn gc_close() {
    while gc_depth { gc_depth = gc_depth - 1; syscall(3, load64(gc_frames + gc_depth * 10272), 0, 0, 0, 0, 0); }
    let i = 0; while i < 2 { if load64(gc_roots + i * 8) >= 0 { syscall(3, load64(gc_roots + i * 8), 0, 0, 0, 0, 0); } i = i + 1; } return 0;
}
