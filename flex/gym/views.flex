// Monolith owns server rendering, form actions, keyed updates and browser SSE.
import "monolith";
import "../../build/flex/gym-style.flex";
import "../../build/flex/gym-camera.flex";

global gu_selected = 0;
global gu_last_hash = -1;
global gu_buffer = 0;
global gu_builder = 0;

fn gu_number(value) { if value < 0 { return m_cat("-", m_int(-value)); } return m_int(value); }
fn gu_bool_attr(value) { if value { return ""; } return 0; }
fn gu_run_class(id) { if id == gu_selected { return "selected"; } return ""; }
fn gu_joint_name(index) { if !index { return "Yaw"; } if index == 1 { return "Shoulder"; } if index == 2 { return "Elbow"; } return "Wrist"; }
fn gu_color(index) { if !index { return "#b9e39c"; } if index == 1 { return "#e0bb80"; } if index == 2 { return "#8abed6"; } return "#c8a0d6"; }
fn gu_case_name(name) { return gg_case_name(name); }
fn gu_cases() {
    let items = ui_items(); let source = pj_parse(gg_case_catalog(), pl_size(gg_case_catalog())); let i = 0;
    while i < pj_count(source) {
        let entry = pj_index(source, i); let row = m_take(16); let id = pj_string_field(entry, "id"); let name = pj_string_field(entry, "name");
        store64(row, m_slice(id, m_len(id))); store64(row + 8, m_slice(name, m_len(name))); ui_item_add(items, row); i = i + 1;
    }
    return items;
}
fn gu_native() { let row = flexdb_get(gm_runs, gu_selected); return row && gg_native_case(flexdb_word(flexdb_cell(row, 0))); }
fn gu_artifact(leaf) { return m_cat(m_cat("/api/gym/runs/", m_int(gu_selected)), m_cat("/artifacts/", leaf)); }
fn gu_metric_label(native) { if native { return "BRICKS DELIVERED"; } return "BUS PACKETS"; }
fn gu_rows() {
    let result = ui_items(); let q = flexdb_query(gm_db); let rows = flexdb_scan(q, gm_runs); let n = flexdb_count(rows); let i = n - 1;
    while i >= pb_max(n - 50, 0) {
        let source = flexdb_at(rows, i); let row = m_take(40); store64(row, load64(source)); let k = 0;
        while k < 4 {
            let value = flexdb_word(flexdb_cell(source, k)); if k != 1 { value = m_slice(value, m_len(value)); }
            store64(row + 8 + k * 8, value); k = k + 1;
        }
        ui_item_add(result, row); i = i - 1;
    }
    flexdb_query_close(q); if !gu_selected && load64(result) { gu_selected = load64(load64(result + 8)); } return result;
}
fn gu_detail() {
    let out = m_take(88); let i = 0; while i < 10 { store64(out + i * 8, "—"); i = i + 1; } store64(out + 80, 0);
    store64(out, 0); let joints = ui_items(); store64(out + 72, joints); let row = flexdb_get(gm_runs, gu_selected);
    if !row { return out; }
    store64(out, gu_selected); store64(out + 8, gu_case_name(flexdb_word(flexdb_cell(row, 0))));
    store64(out + 56, m_slice(flexdb_word(flexdb_cell(row, 2)), m_len(flexdb_word(flexdb_cell(row, 2)))));
    let state = m_slice(flexdb_word(flexdb_cell(row, 3)), m_len(flexdb_word(flexdb_cell(row, 3)))); store64(out + 64, state); store64(out + 16, state);
    let progress = gm_load(row, "progress.json");
    if progress {
        let reason = pj_string_field(progress, "reason"); if !pj_error { store64(out + 16, m_slice(reason, m_len(reason))); }
        if pj_get(progress, "recordingReady") { store64(out + 80, pj_boolean(progress, "recordingReady")); }
        let ms = pj_integer(progress, "timeMs", 0, 1000000000);
        if !pj_error { let fraction = m_int((ms % 1000) / 10); if m_len(fraction) == 1 { fraction = m_cat("0", fraction); } store64(out + 24, m_cat(m_cat(m_int(ms / 1000), "."), m_cat(fraction, " s"))); }
        if pj_get(progress, "serialPackets") { let packets = pj_integer(progress, "serialPackets", 0, 1000000000); if !pj_error { store64(out + 32, m_int(packets)); } }
        let fault = pj_string_field(progress, "fault"); if !pj_error { if !m_len(fault) { fault = "None"; } store64(out + 40, m_slice(fault, m_len(fault))); }
        if gg_native_case(flexdb_word(flexdb_cell(row, 0))) {
            let placed = pj_integer(progress, "placed", 0, 100); let count = pj_integer(progress, "objects", 0, 100);
            if !pj_error { store64(out + 32, m_cat(m_int(placed), m_cat(" / ", m_int(count)))); }
        }
        let plant = pj_get(progress, "plant"); let targets = pj_get(progress, "targets"); i = 0;
        if pj_kind(plant) == 3 && pj_count(plant) == 4 {
            while i < 4 {
                let j = m_take(32); store64(j, i); let p = pj_index(plant, i);
                store64(j + 8, gu_number(pj_integer(p, "tick", 0, 4095))); store64(j + 16, "—");
                if pj_kind(targets) == 3 && pj_count(targets) == 4 { store64(j + 16, gu_number(pj_value(pj_index(targets, i)))); }
                store64(j + 24, gu_number(pj_integer(p, "command", -32767, 32767))); if !pj_error { ui_item_add(joints, j); } i = i + 1;
            }
        }
    }
    let endpoint = gm_load(row, "endpoint.json"); let url = "Starting simulator…";
    let ready = 0;
    if endpoint { let value = pj_string_field(endpoint, "url"); if !pj_error { url = m_slice(value, m_len(value)); ready = 1; } }
    if !ready && (m_eq(state, "running") || m_eq(state, "paused")) { store64(out + 64, "starting"); }
    if !m_eq(state, "running") && !m_eq(state, "paused") { url = m_cat("Recorded endpoint (inactive): ", url); }
    store64(out + 48, url); return out;
}
fn gu_samples() {
    let row = flexdb_get(gm_runs, gu_selected); if !row { return 0; }
    pl_builder(gu_builder, gu_buffer, 32768); gm_samples(row, gu_builder); if load64(gu_builder + 24) { return 0; }
    return pj_parse(gu_buffer, load64(gu_builder + 8));
}
fn gu_curve(samples, joint) {
    if pj_kind(samples) != 3 || !pj_count(samples) { return ""; }
    let count = pj_count(samples); let low = 4096; let high = 0; let i = 0;
    while i < count {
        let plant = pj_get(pj_index(samples, i), "plant"); let tick = pj_integer(pj_index(plant, joint), "tick", 0, 4095);
        if pj_error { return ""; } low = pb_min(low, tick); high = pb_max(high, tick); i = i + 1;
    }
    low = low - 2; high = high + 2; let last = pj_integer(pj_index(samples, count - 1), "timeMs", 0, 1000000000); if pj_error { return ""; } last = pb_max(last, 1);
    let b = m_buffer(); i = 0;
    while i < count {
        let sample = pj_index(samples, i); let ms = pj_integer(sample, "timeMs", 0, 1000000000);
        let tick = pj_integer(pj_index(pj_get(sample, "plant"), joint), "tick", 0, 4095); if pj_error { return ""; }
        if i { m_text(b, " "); } m_text(b, m_int(16 + ms * 668 / last)); m_text(b, ","); m_text(b, m_int(160 - (tick - low) * 140 / (high - low))); i = i + 1;
    }
    return m_data(b);
}
fn gu_indices() { let rows = ui_items(); let i = 0; while i < 4 { let p = m_take(8); store64(p, i); ui_item_add(rows, p); i = i + 1; } return rows; }
fn gu_hash(hash, bytes, size) { let i = 0; while i < size { hash = ((hash ^ load8(bytes + i)) * 16777619) & 0xffffffff; i = i + 1; } return hash; }
fn app_init(path) {
    if !gm_database(path) { return 1; } mono_style = gm_styles(); gu_buffer = alloc(32768); gu_builder = alloc(32); return 0;
}
fn app_tick() {
    let hash = gu_selected; let rows = gu_rows(); let i = 0;
    while i < load64(rows) { let row = load64(rows + 8 + i * 8); hash = gu_hash(hash + load64(row), load64(row + 32), m_len(load64(row + 32))); i = i + 1; }
    let row = flexdb_get(gm_runs, gu_selected);
    if row {
        gr_path(gm_work, flexdb_word(flexdb_cell(row, 2)), "progress.json"); let n = pl_read_file(gm_work, gm_work + 4096, 8192); if n > 0 { hash = gu_hash(hash, gm_work + 4096, n); }
        gr_path(gm_work, flexdb_word(flexdb_cell(row, 2)), "endpoint.json"); n = pl_read_file(gm_work, gm_work + 4096, 8192); if n > 0 { hash = gu_hash(hash, gm_work + 4096, n); }
    }
    if hash == gu_last_hash { return 0; } gu_last_hash = hash; return 1;
}
fn app_action(action, id) {
    if m_eq(action, "launch") {
        let name = mono_field("case"); let seed = m_number(mono_field("seed")); if !gg_case_valid(name) || seed < 0 || seed > 0xffffffff { return 422; }
        let result = gm_start(name, seed); if result < 0 { if result == -8 { return 409; } return 500; } gu_selected = result; return 200;
    }
    let row = flexdb_get(gm_runs, id); if !row { return 404; }
    if m_eq(action, "select") { gu_selected = id; return 200; }
    if m_eq(action, "pause") || m_eq(action, "resume") || m_eq(action, "stop") { if gm_control(row, action) { return 200; } return 409; }
    return 422;
}
view gu_run(row) {
    let id = load64(row); let key = m_cat("run-", m_int(id)); let state = load64(row + 32);
    tr(key, class: gu_run_class(id), data-run: m_int(id)) {
        td(m_cat(key, "-number")) { button(m_cat(key, "-select"), text: m_cat("#", m_int(id)), class: "run-link", action: "select", action_id: id); }
        td(m_cat(key, "-case"), text: gu_case_name(load64(row + 8)));
        td(m_cat(key, "-seed"), text: m_int(load64(row + 16)));
        td(m_cat(key, "-outcome")) { span(m_cat(key, "-badge"), text: state, class: m_cat("badge ", state)); }
    }
}
view gu_case_option(row) { option(m_cat("case-", load64(row)), text: load64(row + 8), value: load64(row)); }
view gu_joint(j) {
    let index = load64(j); let key = m_cat("joint-", m_int(index));
    tr(key) {
        td(m_cat(key, "-name"), text: gu_joint_name(index)); td(m_cat(key, "-tick"), text: load64(j + 8));
        td(m_cat(key, "-target"), text: load64(j + 16)); td(m_cat(key, "-command"), text: load64(j + 24));
    }
}
view app_view() {
    let cases = gu_cases(); let rows = gu_rows(); let detail = gu_detail(); let samples = gu_samples(); let indices = gu_indices(); let id = load64(detail); let state = load64(detail + 64); let native = gu_native();
    let metric_label = gu_metric_label(native);
    div("gym-app") {
        header("header") {
            b("brand", text: "● PuppyBotGym");
            button("navigation-toggle", id: "navigation-toggle", class: "navigation-toggle", type: "button", popovertarget: "site-navigation", aria-label: "Open navigation", aria-controls: "site-navigation", aria-expanded: "false", text: "Workspace ⌄");
            span("connection", class: "connection", text: "Connecting…", data-mono-status: "");
        }
        nav("navigation", id: "site-navigation", class: "navigation-panel", popover: "auto", aria-label: "Primary") {
            div("navigation-experiments", class: "navigation-group") { h2("navigation-experiments-label", text: "Experiments"); a("navigation-rollouts", id: "nav-rollouts", href: "/", text: "Simulation rollouts"); }
            div("navigation-tools", class: "navigation-group") { h2("navigation-tools-label", text: "Tools"); a("navigation-live", id: "nav-live", href: "/live", text: "Live camera test"); }
        }
        main("live-workspace", id: "live-workspace") {
            div("live-eyebrow", class: "eyebrow", text: "Vision workspace"); h1("live-title", text: "See what the model sees.");
            p("live-intro", class: "muted", text: "Test the detector with this computer’s camera. Frames stay on this machine and do not control the robot.");
            div("live-layout", class: "live-layout") {
                section("live-camera-panel", class: "panel") {
                    div("live-toolbar", class: "toolbar") { h2("live-camera-title", text: "Camera"); span("live-status", id: "live-status", class: "badge", role: "status", text: "Camera off"); }
                    div("live-stage", class: "live-stage") {
                        video("live-video", id: "live-video", autoplay: "", muted: "", playsinline: "", aria-label: "Live camera preview");
                        canvas("live-canvas", id: "live-canvas", width: "640", height: "480", aria-label: "Latest analyzed camera frame with object boxes");
                        p("live-empty", id: "live-empty", class: "muted", text: "Start the camera to try object detection.");
                    }
                    p("live-metrics", id: "live-metrics", class: "muted", text: "Each set of boxes belongs to the frame shown above.");
                }
                aside("live-settings", class: "panel") {
                    h2("live-settings-title", text: "Live test"); label("live-model-label", for: "live-model", text: "Detector");
                    select("live-model", id: "live-model", disabled: "") { option("live-model-current", value: gv_name, text: gv_name); }
                    p("live-model-help", class: "muted", text: "Boxes show the model’s object labels and confidence.");
                    label("live-device-label", for: "live-device", text: "Camera"); select("live-device", id: "live-device") { option("live-default-device", value: "", text: "Default camera"); }
                    button("live-start", id: "live-start", class: "primary", type: "button", text: "Start camera");
                    button("live-stop", id: "live-stop", class: "live-stop", type: "button", disabled: "", text: "Stop camera");
                    p("live-error", id: "live-error", class: "error", role: "alert", text: "");
                    div("live-detections-title", class: "eyebrow", text: "Detected objects"); ul("live-detections", id: "live-detections");
                    p("live-note", class: "muted", text: "Camera access requires localhost or HTTPS. No frames are saved by Live.");
                }
            }
        }
        main("workspace", id: "workspace") {
            div("eyebrow", class: "eyebrow", text: "Experiment workspace"); h1("heading", text: "Run a case. Inspect the outcome.");
            p("intro", class: "muted", text: "Launch servo checks or camera-based room discovery and pickup. Each rollout has its own process, seed, and recordings.");
            div("layout", class: "layout") {
                aside("sidebar") {
                    form("launch", id: "launch", class: "panel", action: "launch") {
                        h2("launch-heading", text: "New rollout"); label("case-label", text: "Case", for: "case");
                        select("case", id: "case", name: "case", required: "") {
                            each entry in cases { use gu_case_option(entry); }
                        }
                        p("case-description", class: "muted", text: "Discover house and collect builds its map from the wrist camera. Native scenes run at maximum speed and record a video.");
                        label("seed-label", text: "Seed", for: "seed"); input("seed", id: "seed", name: "seed", type: "number", min: "0", max: "4294967295", value: "42", required: "");
                        button("start", id: "start", text: "Start rollout ↗", class: "primary", type: "submit");
                        div("error", id: "error", role: "alert", data-mono-error: "");
                    }
                    section("backend", class: "panel") {
                        div("backend-eyebrow", class: "eyebrow", text: "Simulation backends"); h2("backend-title", text: "Servo plant + native scenes");
                        p("backend-description", class: "muted", text: "Servo checks exercise encoder feedback and faults. Native scenes add the apartment, wrist RGB, physical contacts, mapping, and pickup.");
                        p("backend-scope", class: "muted", text: "The native arm is kinematic with swept collision checks; loose objects use contact dynamics.");
                    }
                }
                div("results") {
                    section("run-list", class: "panel") {
                        div("run-toolbar", class: "toolbar") { h2("runs-title", text: "Rollouts"); span("count", id: "count", class: "muted", text: m_cat(m_int(load64(rows)), " recent rollouts")); }
                        div("runs-wrap", class: "tablewrap") {
                            table("runs-table") {
                                thead("runs-head") { tr("runs-head-row") { th("run-th", text: "Run"); th("case-th", text: "Case"); th("seed-th", text: "Seed"); th("outcome-th", text: "Outcome"); } }
                                tbody("runs", id: "runs") { each row in rows { use gu_run(row); } }
                            }
                        }
                        empty("empty", id: "empty", text: "No rollouts yet. Choose a case to begin.", hidden: load64(rows) > 0);
                    }
                    section("detail", id: "detail", class: "panel", hidden: !id) {
                        div("detail-toolbar", class: "toolbar") {
                            div("detail-title") { div("run-title", id: "runTitle", class: "eyebrow", text: m_cat("ROLLOUT #", m_int(id))); h2("run-case", id: "runCase", text: load64(detail + 8)); }
                            div("actions", class: "actions") {
                                button("pause", id: "pause", text: "Pause", action: "pause", action_id: id, disabled: gu_bool_attr(!m_eq(state, "running")));
                                button("resume", id: "resume", text: "Resume", action: "resume", action_id: id, disabled: gu_bool_attr(!m_eq(state, "paused")));
                                button("stop", id: "stop", text: "Stop", action: "stop", action_id: id, disabled: gu_bool_attr(!m_eq(state, "running") && !m_eq(state, "paused")));
                            }
                        }
                        p("reason", id: "reason", class: "muted", text: load64(detail + 16));
                        div("metrics", class: "metrics") {
                            div("time-metric", class: "metric") { small("time-label", text: "SIMULATION TIME"); b("time", id: "time", text: load64(detail + 24)); }
                            div("packets-metric", class: "metric") { small("packets-label", text: metric_label); b("packets", id: "packets", text: load64(detail + 32)); }
                            div("fault-metric", class: "metric") { small("fault-label", text: "CONTROLLER FAULT"); b("fault", id: "fault", text: load64(detail + 40)); }
                        }
                        if native && load64(detail + 80) {
                            h2("video-title", text: "Simulation recording");
                            video("mission-video", id: "mission-video", controls: "", preload: "metadata", src: gu_artifact("mission.mp4")) { }
                            p("video-download") { a("video-link", href: gu_artifact("mission.mp4"), text: "Open recording"); }
                            img("outcome-image", class: "native-outcome", src: gu_artifact("outcome.png"), alt: "Final simulator view with the TCP camera");
                        }
                        h2("plot-title", text: "Encoder trace");
                        svg("plot", id: "plot", viewbox: "0 0 700 180", role: "img", aria-label: "Recorded encoder positions over simulation steps") {
                            each index in indices { polyline(m_cat("curve-", m_int(load64(index))), points: gu_curve(samples, load64(index)), fill: "none", stroke: gu_color(load64(index)), stroke-width: "2"); }
                        }
                        div("legend", class: "legend") {
                            each index in indices { span(m_cat("legend-", m_int(load64(index)))) { i(m_cat("dot-", m_int(load64(index))), class: m_cat("joint-", m_int(load64(index)))); span(m_cat("name-", m_int(load64(index))), text: gu_joint_name(load64(index))); } }
                        }
                        p("plot-caption", class: "muted", text: "Each joint uses its own vertical range. The preview samples up to 32 recorded observations.");
                        div("joints-wrap", class: "tablewrap") {
                            table("joints-table") {
                                thead("joints-head") { tr("joints-head-row") { th("joint-name-th", text: "Joint"); th("joint-tick-th", text: "Encoder tick"); th("joint-target-th", text: "Case target"); th("joint-command-th", text: "Command"); } }
                                tbody("joints", id: "joints") { each j in load64(detail + 72) { use gu_joint(j); } }
                            }
                        }
                        div("endpoint-panel", class: "endpoint") {
                            p("endpoint-help", class: "muted", text: "The robot control UI connects separately to this bot while its rollout is active:"); code("endpoint", id: "endpoint", text: load64(detail + 48));
                            p("directory-label", class: "muted", text: "Run artifacts"); code("directory", id: "directory", text: load64(detail + 56));
                        }
                    }
                }
            }
        }
    }
}
