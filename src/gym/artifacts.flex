// Bounded nonblocking playback of retained native rollout artifacts.
import "../runtime/server.flex";

global ga_jobs = 0;
global ga_buffer = 0;

fn ga_init() {
    ga_jobs = alloc(768); ga_buffer = alloc(16384); let i = 0;
    while i < 32 { store64(ga_jobs + i * 24, -1); i = i + 1; } return 0;
}
fn ga_close(job) {
    if load64(job) >= 0 { syscall(3, load64(job), 0, 0, 0, 0, 0); store64(job, -1); } return 0;
}
fn ga_poll(wall) {
    let i = 0;
    while i < 32 {
        let job = ga_jobs + i * 24; let c = pn_clients + i * 65536;
        if load64(job) >= 0 {
            if load64(c) != load64(job + 16) || pb_vget(c, 1) != 6 { ga_close(job); }
            else if pb_vget(c, 3) == pb_vget(c, 4) {
                let n = syscall(0, load64(job), ga_buffer, pb_min(load64(job + 8), 16384), 0, 0, 0);
                if n > 0 {
                    if pnet_queue(c, ga_buffer, n, wall) < 0 { ga_close(job); }
                    else {
                        store64(job + 8, load64(job + 8) - n);
                        if !load64(job + 8) { ga_close(job); pb_vset(c, 1, 3); }
                    }
                } else if n != -4 { ga_close(job); pnet_close(c); }
            }
        }
        i = i + 1;
    }
    return 0;
}
fn ga_request(c, wall) {
    let path = c + 160; if !pl_equal(c + 128, "GET") { return 0; }
    let history = pl_starts(path, "/api/gym/history/");
    if !history && !pl_starts(path, "/api/gym/runs/") { return 0; }
    let text = path + 14; if history { text = path + 17; }
    let n = 0; while load8(text + n) >= 48 && load8(text + n) <= 57 { n = n + 1; }
    let id = pl_integer(text, n); if pl_bad_number || id < 1 || !pl_starts(text + n, "/artifacts/") { return 0; }
    let leaf = text + n + 11; let mime = 0;
    if pl_equal(leaf, "mission.mp4") { mime = "video/mp4"; }
    if pl_equal(leaf, "outcome.png") { mime = "image/png"; }
    if !mime { pnet_error(c, 404, "unknown artifact", wall); return 1; }
    let fd = -1;
    if history { fd = gc_artifact(id, leaf); }
    else {
        let row = flexdb_get(gm_runs, id); if !row { pnet_error(c, 404, "unknown rollout", wall); return 1; }
        gr_path(gm_work, flexdb_word(flexdb_cell(row, 2)), leaf); fd = syscall(2, gm_work, 0xa0000, 0, 0, 0, 0);
    }
    if fd < 0 { pnet_error(c, 404, "artifact is not available", wall); return 1; }
    let size = syscall(8, fd, 0, 2, 0, 0, 0); let start = 0; let end = size - 1; let partial = 0;
    let range = ph_header(c + 512, pb_vget(c, 10), "range"); let valid = !ph_duplicates;
    if range {
        let length = ph_value_size; let dash = ph_find(range, length, "-", 1); partial = 1;
        if length < 7 || !pl_starts(range, "bytes=") || dash < 6 { valid = 0; }
        else {
            start = pl_integer(range + 6, dash - 6); if pl_bad_number { valid = 0; }
            if dash + 1 < length { end = pl_integer(range + dash + 1, length - dash - 1); if pl_bad_number { valid = 0; } }
        }
    }
    if !valid || size < 1 || start < 0 || start >= size || end < start {
        syscall(3, fd, 0, 0, 0, 0, 0); pnet_error(c, 400, "invalid artifact range", wall); return 1;
    }
    end = pb_min(end, size - 1); syscall(8, fd, start, 0, 0, 0, 0);
    let b = pn_builder; pl_builder(b, pn_head, 4096); pl_text(b, "HTTP/1.1 ");
    if partial { pl_text(b, "206 Partial Content\r\n"); } else { pl_text(b, "200 OK\r\n"); }
    pl_text(b, "Content-Type: "); pl_text(b, mime); pl_text(b, "\r\nContent-Length: "); pl_uint(b, end - start + 1);
    pl_text(b, "\r\nAccept-Ranges: bytes\r\nCache-Control: no-store\r\nConnection: close\r\n");
    if partial { pl_text(b, "Content-Range: bytes "); pl_uint(b, start); pl_char(b, 45); pl_uint(b, end); pl_char(b, 47); pl_uint(b, size); pl_text(b, "\r\n"); }
    pl_text(b, "\r\n");
    let job = ga_jobs + ((c - pn_clients) / 65536) * 24; ga_close(job);
    if pnet_queue(c, pn_head, load64(b + 8), wall) < 0 { syscall(3, fd, 0, 0, 0, 0, 0); return 1; }
    store64(job, fd); store64(job + 8, end - start + 1); store64(job + 16, load64(c)); pb_vset(c, 1, 6); return 1;
}
