// Gym lifecycle/artifacts around the same native simulator used by sim.flex.
import "../gym/runner.flex";

global ps_gym_directory = 0;
global ps_gym_context = 0;
global ps_gym_progress = 0;
global ps_gym_result = 0;
global ps_gym_control = 0;
global ps_gym_journal = -1;
global ps_gym_next = 0;
global ps_gym_cancelled = 0;
global ps_gym_started = 0;
global ps_gym_limit = 0;

fn ps_gym_path(leaf) { return h_cat3(ps_gym_directory, "/", leaf); }
fn ps_gym_status(state, reason, passed) {
    let c = ps_gym_context; let b = c + 256; pl_builder(b, c + 8192, 8192);
    pl_text(b, "{\"schema\":\"puppybotgym.run.v1\",\"case\":"); pj_text(b, ps_catalog_entries + ps_case_index * 768);
    pl_text(b, ",\"seed\":"); pl_uint(b, ps_case_seed); pl_text(b, ",\"backend\":\"flexscript-kinematic-contact-v1\",\"articulatedPhysics\":false,\"contactPhysics\":true,\"status\":"); pj_text(b, state);
    pl_text(b, ",\"reason\":"); pj_text(b, reason); pl_text(b, ",\"passed\":"); pj_bool_text(b, passed);
    pl_text(b, ",\"recordingReady\":"); pj_bool_text(b, ps_video_path && !ps_video_pid && !ps_video_failed);
    pl_text(b, ",\"stepMs\":20,\"step\":"); pl_uint(b, ps_step); pl_text(b, ",\"timeMs\":"); pl_uint(b, ps_step * 20);
    pl_text(b, ",\"wallMs\":"); pl_uint(b, pl_now() - ps_gym_started); pl_text(b, ",\"stepLimit\":"); pl_uint(b, ps_gym_limit);
    pl_text(b, ",\"sampleStride\":25,\"placed\":"); pl_uint(b, ps_case_placed); pl_text(b, ",\"objects\":"); pl_uint(b, ps_case_count);
    pl_text(b, ",\"scans\":"); pl_uint(b, ps_discovery_scans); pl_text(b, ",\"protectiveStops\":"); pl_uint(b, ps_discovery_stops);
    pl_text(b, ",\"fault\":"); let fault = ""; if load64(ps_physics + 192) || ps_vehicle_fault { fault = "physics/query fault"; } pj_text(b, fault);
    pl_text(b, ",\"plant\":"); gr_plant_json(c, b); pl_text(b, "}\n");
    if load64(b + 24) { return 0; } return !pl_atomic_file(ps_gym_progress, c + 8192, load64(b + 8));
}
fn ps_gym_sample() {
    if !ps_gym_directory { return 1; }
    let c = ps_gym_context; let b = c + 288; pl_builder(b, c + 16384, 4096);
    pl_text(b, "{\"step\":"); pl_uint(b, ps_step); pl_text(b, ",\"timeMs\":"); pl_uint(b, ps_step * 20); pl_text(b, ",\"plant\":"); gr_plant_json(c, b); pl_text(b, "}\n");
    if load64(b + 24) || pl_write(ps_gym_journal, c + 16384, load64(b + 8)) { return 0; }
    return ps_gym_status("running", ps_case_reason, 0);
}
fn ps_gym_start(steps, model, environment) {
    if !ps_gym_directory { return 1; }
    ps_gym_context = alloc(24576); let c = ps_gym_context; pb_vset(c, 2, ps_plant); pb_vset(c, 3, ps_bus);
    ps_gym_progress = ps_gym_path("progress.json"); ps_gym_result = ps_gym_path("result.json"); ps_gym_control = ps_gym_path("control");
    ps_gym_started = pl_now(); ps_gym_limit = steps;
    ps_gym_journal = syscall(2, ps_gym_path("observations.jsonl"), 0x800c1, 384, 0, 0, 0);
    if ps_gym_journal < 0 || !gr_copy_firmware("/proc/self/exe", ps_gym_path("simulator.elf")) { return 0; }
    let b = c + 256; pl_builder(b, c + 8192, 8192); pc_emit(b, ps_config); pl_char(b, 10);
    if load64(b + 24) || pl_atomic_file(ps_gym_path("config.json"), c + 8192, load64(b + 8)) { return 0; }
    pl_builder(b, c + 8192, 8192); pl_text(b, "{\"schema\":\"puppybotgym.endpoint.v1\",\"backend\":\"flexscript-kinematic-contact-v1\",\"url\":");
    pj_text(b, h_cat3("ws://127.0.0.1:", h_int(pn_port), "/ws")); pl_text(b, ",\"stateUrl\":"); pj_text(b, h_cat3("http://127.0.0.1:", h_int(pn_port), "/api/sim/state"));
    pl_text(b, ",\"simulatorPid\":"); pl_int(b, syscall(39, 0, 0, 0, 0, 0, 0)); pl_text(b, "}\n");
    if load64(b + 24) || pl_atomic_file(ps_gym_path("endpoint.json"), c + 8192, load64(b + 8)) { return 0; }
    pl_builder(b, c + 8192, 8192); pl_text(b, "{\"schema\":\"puppybotgym.manifest.v1\",\"backend\":\"flexscript-kinematic-contact-v1\",\"articulatedPhysics\":false,\"contactPhysics\":true,\"case\":");
    pj_text(b, ps_catalog_entries + ps_case_index * 768); pl_text(b, ",\"seed\":"); pl_uint(b, ps_case_seed); pl_text(b, ",\"stepLimit\":"); pl_uint(b, steps);
    pl_text(b, ",\"simulator\":\"simulator.elf\",\"model\":"); pj_text(b, model); pl_text(b, ",\"environment\":"); if environment { pj_text(b, environment); } else { pl_text(b, "null"); }
    pl_text(b, ",\"caseFile\":"); pj_text(b, ps_catalog_entries + ps_case_index * 768 + 256);
    pl_text(b, ",\"policy\":\"native-case-controller\",\"fullTrace\":\"simulation.jsonl\",\"video\":\"mission.mp4\",\"capture\":\"outcome.png\",\"assetPathsAreLive\":true}\n");
    if load64(b + 24) || pl_atomic_file(ps_gym_path("manifest.json"), c + 8192, load64(b + 8)) || !ps_gym_sample() { return 0; }
    if ps_paused { return ps_gym_status("paused", "simulation time is frozen", 0); } return 1;
}
fn ps_gym_poll(wall) {
    if !ps_gym_directory || wall < ps_gym_next { return 1; } ps_gym_next = wall + 20;
    let text = ps_gym_context + 2048; let size = pl_read_file(ps_gym_control, text, 32); if size == -2 { return 1; } if size < 0 { return 0; }
    // Consume the command once; an unchanged file cannot repeatedly reset time.
    if syscall(87, ps_gym_control, 0, 0, 0, 0, 0) { return 0; }
    if pl_equal(text, "stop") { ps_gym_cancelled = 1; return 0; }
    if pl_equal(text, "pause") { ps_paused = 1; return ps_gym_status("paused", "simulation time is frozen", 0); }
    if pl_equal(text, "resume") { ps_paused = 0; return ps_gym_status("running", ps_case_reason, 0); } return 0;
}
fn ps_gym_finish(result) {
    if !ps_gym_directory { return result; }
    let state = "failed"; let reason = ps_case_reason; let passed = !result && ps_case_passed;
    if passed { state = "passed"; } if ps_gym_cancelled { state = "cancelled"; reason = "rollout stopped"; passed = 0; result = 130; }
    if syscall(74, ps_gym_journal, 0, 0, 0, 0, 0) { state = "error"; reason = "cannot sync Gym observation journal"; passed = 0; result = 1; }
    syscall(3, ps_gym_journal, 0, 0, 0, 0, 0);
    if !ps_gym_status(state, reason, passed) || pl_atomic_file(ps_gym_result, ps_gym_context + 8192, load64(ps_gym_context + 264)) { result = 1; }
    return result;
}
