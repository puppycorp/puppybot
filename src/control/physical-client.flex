// Experimental hybrid: a visual policy navigates until an RGB detection, then
// yields to the simulator's existing physical collection controller. No world
// poses, object identifiers, contacts or containment are fed to the policy.
// The simulator's terminal status does not establish a successful delivery;
// inspect the separate trace with the independent manipulation auditor.
import "environment.flex";
import "physical-feedback.flex";
import "physical-sensor-gate.flex";
import "progress-guard.flex";
global pc_process = 0;
global pc_sequence = 0;
global pc_output = 0;
global pc_state = 0;
global pc_header = 0;
global pc_request = 0;
global pc_hidden = 0;
global pc_journal = 0;
global pc_last_frame = -1;
global pc_arm = 0;
global pc_command_type = 0;
global pc_command_hold = 0;
global pc_command_steering = 0;
global pc_command_speed = 0;
global pc_actors = 0;
global pc_actor_stem = 0;
global pc_sim_sha = 0;
global pc_case_sha = 0;
global pc_env_sha = 0;
global pc_model_sha = 0;
global pc_binary_sha = 0;
global pc_receipt_sha = 0;
global pc_asset_sha = 0;
global pc_rescan_enabled = 0;
global pc_rescan_attempts = 0;
global pc_rescan_handoff = 0;
global pc_rescan_stop_reason = 0;
global pc_terminal_failure = 0;
global pc_terminal_failure_invalid = 0;

fn pc_observe() {
    let fd = load64(pc_process + 8); vc_io(1, fd, pc_header, 32); let size = load64(pc_header);
    vc_require(size > 0 && size <= 65536 && load64(pc_header + 8) == 640 * 480 * 3 && load64(pc_header + 16) == pc_sequence && !load64(pc_header + 24), "invalid physical-agent frame");
    vc_io(1, fd, ve_json, size); store8(ve_json + size, 0); vc_io(1, fd, ve_rgb, 640 * 480 * 3);
    pc_state = pj_parse(ve_json, size); vc_require(pc_state && pl_equal(pj_string_field(pc_state, "schema"), "puppybot.physical-agent.v1"), "invalid physical-agent schema");
    vc_require(vc_json_int(pc_state, "sequence", 0) == pc_sequence, "physical-agent journal sequence mismatch");
    let owner = vc_json_int(pc_state, "owner", 0); let ack = vc_json_int(pc_state, "ack", 0); let valid = pj_boolean(pc_state, "imageValid");
    vc_require(!pj_error && owner >= 0 && owner <= 2 && pc_status_ok(pc_command_type, owner, ack), "invalid physical-agent status");
    let drive = pj_get(pc_state, "driveCommand"); vc_require(pj_kind(drive) == 3 && pj_count(drive) == 3, "missing drive command"); let i = 0; let commands = alloc(24);
    while i < 3 { let node = pj_index(drive, i); vc_require(pj_kind(node) == 1, "invalid drive command"); store64(commands + i * 8, pj_value(node)); i = i + 1; }
    vc_require(pc_drive_ok(pc_command_type, ack, load64(commands), load64(commands + 8), load64(commands + 16), pc_command_steering, pc_command_speed), "drive command did not match policy or stop"); syscall(11, commands, 24, 0, 0, 0, 0);
    if !owner {
        let frame = vc_json_int(pc_state, "cameraFrame", 0); let total = vc_json_int(pc_state, "totalSteps", 0);
        let driving = pj_boolean(pc_state, "cameraDriving"); let still = pj_boolean(pc_state, "cameraStill");
        let joints = pj_get(pc_state, "jointTicks"); vc_require(pj_kind(joints) == 3 && pj_count(joints) == 4, "missing arm encoder feedback");
        i = 0; let unchanged = 1;
        while i < 4 { let node = pj_index(joints, i); vc_require(pj_kind(node) == 1, "invalid arm encoder feedback"); let tick = pj_value(node);
            if pc_last_frame < 0 { store64(pc_arm + i * 8, tick); } else if tick != load64(pc_arm + i * 8) { unchanged = 0; } i = i + 1; }
        vc_require(!pj_error && valid && pc_sensor_ok(driving, still, frame, total, pc_last_frame, pc_command_type, pc_command_hold, unchanged), "stale camera frame or changing driving pose");
        pc_last_frame = frame; vc_resize_to(ve_rgb, ve_image, ve_image_side);
        pc_feedback(pj_get(pc_state, "driveCommand"), ve_previous, ve_feedback);
    } else { vc_require(!valid, "collector frame must not mutate its camera"); }
    vc_require(!pl_write(pc_journal, ve_json, size), "cannot write physical-agent journal"); return ack;
}
fn pc_command(command, steering, speed, hold) {
    pc_command_type = command; pc_command_hold = hold; pc_command_steering = steering; pc_command_speed = speed;
    pc_sequence = pc_sequence + 1; pb_zero(pc_request, 64); store64(pc_request, command); store64(pc_request + 8, pc_sequence);
    store64(pc_request + 16, steering); store64(pc_request + 24, speed); store64(pc_request + 32, hold); store64(pc_request + 48, 4);
    vc_io(0, load64(pc_process + 8), pc_request, 64); return pc_observe();
}
fn pc_record_input() {
    // These are exactly the bytes provided to the actor, including its
    // recurrent state before inference. A fresh output directory is required.
    pc_actor_stem = vc_path(pc_actors, vc_concat("actor-", vc_int(pc_sequence)));
    vc_write(vc_concat(pc_actor_stem, ".rgb"), ve_image, ve_image_bytes);
    vc_write(vc_concat(pc_actor_stem, ".feedback"), ve_feedback, 28);
    vc_write(vc_concat(pc_actor_stem, ".hidden"), pc_hidden, ve_memory_width * 4); return 0;
}
fn pc_record_action(action) { return vc_write(vc_concat(pc_actor_stem, ".action"), action, 8); }
// At the navigation limit, an opt-in recovery performs at most two stopped,
// fresh RGB checks. The clock is simulator ticks, not wall time. A detection
// can hand control to the collector, but is not a verified pickup or delivery.
// There is no autonomous search maneuver and no physical-hardware stop proof.
fn pc_stopped_rescan() {
    let now = vc_json_int(pc_state, "totalSteps", 0); let guard = alloc(72);
    vc_require(now > 0 && vg_init(guard, now - 1, 1, 4, 2), "cannot initialize stopped-rescan guard");
    let decision = vg_step(guard, now, 0, 1, 0);
    while decision == 1 {
        pc_rescan_attempts = pc_rescan_attempts + 1;
        let before = now;
        let ack = pc_command(6, 0, 0, 0); now = vc_json_int(pc_state, "totalSteps", 0);
        // Accepted handoffs carry no navigation image, so pc_sensor_ok cannot
        // enforce the stop-and-rescan ticks on that response. Require them here
        // before allowing the collector to continue; stop it on mismatch.
        if now != before + 2 {
            let reason = 3; if now >= before + 4 { reason = 4; }
            vg_stop(guard, reason); pc_rescan_stop_reason = reason; return 0;
        }
        let result = 2; if ack == 3 { result = 1; }
        decision = vg_step(guard, now, 0, 1, result);
        if decision == 3 { pc_rescan_stop_reason = load64(guard + 32); return 0; }
        if ack == 3 { pc_rescan_handoff = 1; return 1; }
        vc_require(ack == 2 && !decision, "invalid stopped-rescan result");
        // Advance one stopped tick before retrying; the ordinary camera and
        // drive echo checks apply, so stale observations do not get reused.
        vc_require(pc_command(2, 0, 0, 1) == 1, "cannot advance stopped rescan");
        now = vc_json_int(pc_state, "totalSteps", 0); decision = vg_step(guard, now, 0, 1, 0);
    }
    vc_require(0, "invalid stopped-rescan state"); return 0;
}
// Copy before the stop response replaces the JSON parser's input buffers.
// An absent field is an older peer or a terminal result without failure detail.
fn pc_remember_terminal_failure() {
    let node = pj_get(pc_state, "collectorFailure"); if !node { return 0; }
    if pj_kind(node) != 2 { pc_terminal_failure_invalid = 1; return 0; }
    let value = pj_value(node); let size = pj_count(node);
    // Bound escaped JSON output as well as the input, and reject embedded NUL.
    if !size || size > 128 || pl_size(value) != size { pc_terminal_failure_invalid = 1; return 0; }
    pc_terminal_failure = alloc(size + 1); vc_copy(pc_terminal_failure, value, size); store8(pc_terminal_failure + size, 0); return 1;
}
fn pc_pin_inputs(simulator, model, case_path, environment) {
    pc_sim_sha = vc_file_sha(simulator); pc_case_sha = vc_file_sha(case_path); pc_env_sha = vc_file_sha(environment);
    pc_model_sha = vc_file_sha(vc_path(model, "weights.bin")); pc_binary_sha = vc_file_sha(vc_path(model, "policy"));
    pc_receipt_sha = vc_file_sha(vc_path(model, "receipt.json")); pc_asset_sha = vc_file_sha("build/flex/sim/puppybot.bin");
    let b = alloc(32); let text = alloc(8192); pl_builder(b, text, 8192);
    pl_text(b, "{\"simulatorSHA256\":"); pj_text(b, pc_sim_sha); pl_text(b, ",\"caseSHA256\":"); pj_text(b, pc_case_sha);
    pl_text(b, ",\"environmentSHA256\":"); pj_text(b, pc_env_sha); pl_text(b, ",\"weightsSHA256\":"); pj_text(b, pc_model_sha);
    pl_text(b, ",\"policySHA256\":"); pj_text(b, pc_binary_sha); pl_text(b, ",\"receiptSHA256\":"); pj_text(b, pc_receipt_sha);
    pl_text(b, ",\"robotAssetSHA256\":"); pj_text(b, pc_asset_sha); pl_text(b, ",\"cameraPitch\":82,\"contactFeedback\":\"unavailable-forced-zero\",\"stoppedRescanEnabled\":");
    pj_bool_text(b, pc_rescan_enabled); pl_text(b, "}\n");
    vc_require(!load64(b + 24), "input manifest exceeds limit"); vc_write(vc_path(pc_output, "inputs.json"), text, load64(b + 8)); return 0;
}
fn pc_check_inputs(simulator, model, case_path, environment) {
    vc_require(pl_equal(vc_file_sha(simulator), pc_sim_sha) && pl_equal(vc_file_sha(case_path), pc_case_sha) && pl_equal(vc_file_sha(environment), pc_env_sha), "simulator or scene changed during run");
    vc_require(pl_equal(vc_file_sha(vc_path(model, "weights.bin")), pc_model_sha) && pl_equal(vc_file_sha(vc_path(model, "policy")), pc_binary_sha) && pl_equal(vc_file_sha(vc_path(model, "receipt.json")), pc_receipt_sha) && pl_equal(vc_file_sha("build/flex/sim/puppybot.bin"), pc_asset_sha), "model or robot asset changed during run");
    let root = vc_json_file(vc_path(model, "receipt.json")); let kernels = pj_get(root, "kernels"); let child = pj_value(kernels);
    vc_require(pj_kind(kernels) == 4 && pj_count(kernels) >= 5, "model kernel manifest missing");
    while child { let name = load64(child + 32); vc_require(!pl_starts(name, "/") && !pl_starts(name, "..") && pl_equal(vc_file_sha(vc_path(vc_path(model, "kernels"), name)), pj_value(child)), "model kernel changed during run"); child = load64(child + 24); } return 0;
}
fn pc_rescan_reason(reason) {
    if !reason { return "none"; } if reason == 1 { return "invalid sensor"; }
    if reason == 2 { return "attempts exhausted"; } if reason == 3 { return "protocol error"; }
    if reason == 4 { return "recovery timeout"; } if reason == 5 { return "unacknowledged recovery"; }
    return "unknown";
}
fn pc_result(actions, handoff, terminal, nav_limit, poll_limit, trace_sha) {
    let b = alloc(32); let text = alloc(1536); pl_builder(b, text, 1536);
    pl_text(b, "{\"policyActions\":"); pl_int(b, actions); pl_text(b, ",\"handoff\":"); pj_bool_text(b, handoff);
    pl_text(b, ",\"collectorTerminal\":"); pj_bool_text(b, terminal); pl_text(b, ",\"navigationActionLimit\":"); pl_int(b, nav_limit); pl_text(b, ",\"collectorPollLimit\":"); pl_int(b, poll_limit);
    pl_text(b, ",\"stoppedRescanEnabled\":"); pj_bool_text(b, pc_rescan_enabled); pl_text(b, ",\"stoppedRescanAttempts\":"); pl_int(b, pc_rescan_attempts);
    pl_text(b, ",\"stoppedRescanHandoff\":"); pj_bool_text(b, pc_rescan_handoff); pl_text(b, ",\"stoppedRescanStopReason\":"); pl_int(b, pc_rescan_stop_reason);
    pl_text(b, ",\"stoppedRescanStopReasonText\":"); pj_text(b, pc_rescan_reason(pc_rescan_stop_reason));
    if pc_terminal_failure { pl_text(b, ",\"collectorFailure\":"); pj_text(b, pc_terminal_failure); }
    if pc_terminal_failure_invalid { pl_text(b, ",\"collectorFailureReportInvalid\":true"); }
    pl_text(b, ",\"stopCommandAcknowledged\":true,\"outcome\":\"unverified\",\"traceSHA256\":"); pj_text(b, trace_sha); pl_text(b, "}\n");
    vc_require(!load64(b + 24), "result exceeds limit"); return vc_write(vc_path(pc_output, "result.json"), text, load64(b + 8));
}
fn pc_stop() {
    let ack = pc_command(3, 0, 0, 0); vc_require(ack == 7 && vc_json_int(pc_state, "owner", 0) == 2, "simulated stop request not acknowledged");
    vc_finish(pc_process, 10000); vc_finish(ve_policy, 10000); return 0;
}
fn main(argc, argv) {
    vc_init(argc, argv); vc_require(argc == 7 && pl_equal(load64(argv + 48), "--allow-zero-contact"), "contact feedback is unavailable; diagnostic usage: physical-client SIMULATOR MODEL CASE_JSON ENVIRONMENT_BIN NEW_OUTPUT_DIRECTORY --allow-zero-contact");
    let nav_limit = 300; let poll_limit = 1500; let value = pl_environment(argc, argv, "PUPPYBOT_PHYSICAL_NAV_LIMIT");
    if value { nav_limit = pl_integer(value, pl_size(value)); vc_require(!pl_bad_number && nav_limit >= 1 && nav_limit <= 300, "invalid physical navigation limit"); }
    value = pl_environment(argc, argv, "PUPPYBOT_PHYSICAL_POLL_LIMIT");
    if value { poll_limit = pl_integer(value, pl_size(value)); vc_require(!pl_bad_number && poll_limit >= 1 && poll_limit <= 1500, "invalid physical collector limit"); }
    value = pl_environment(argc, argv, "PUPPYBOT_PHYSICAL_GUARDED_RESCAN");
    if value { vc_require(pl_equal(value, "0") || pl_equal(value, "1"), "invalid stopped-rescan opt-in"); pc_rescan_enabled = pl_equal(value, "1"); }
    let simulator = load64(argv + 8); let model = load64(argv + 16); let case_path = load64(argv + 24); let environment = load64(argv + 32); pc_output = load64(argv + 40);
    vc_mkdir(pc_output); pc_actors = vc_path(pc_output, "actors"); vc_mkdir(pc_actors); ve_open_buffers(); pc_header = alloc(32); pc_request = alloc(64); pc_arm = alloc(32); pc_hidden = alloc(ve_memory_width * 4); pb_zero(pc_hidden, ve_memory_width * 4); pb_zero(ve_previous, 8);
    pc_journal = syscall(2, vc_path(pc_output, "physical-agent.jsonl"), 0x800c1, 384, 0, 0, 0); vc_require(pc_journal >= 0, "cannot create physical-agent journal");
    pc_pin_inputs(simulator, model, case_path, environment); ve_policy_open(model, pc_output); let args = vc_args(); vc_add(args, simulator); vc_add(args, "--hidden"); vc_add(args, "--case-file"); vc_add(args, case_path);
    vc_add(args, "--environment"); vc_add(args, environment); vc_add(args, "--steps"); vc_add(args, "1000000"); vc_add(args, "--bind"); vc_add(args, "127.0.0.1:0");
    vc_add(args, "--agent-fd"); vc_add(args, "3"); vc_add(args, "--agent-physical"); vc_add(args, "--camera-pitch"); vc_add(args, "82"); vc_add(args, "--localization"); vc_add(args, "wheel-drift"); vc_add(args, "--no-visual-odometry");
    vc_add(args, "--record"); vc_add(args, vc_path(pc_output, "trace.jsonl")); pc_process = vc_spawn(args, vc_path(pc_output, "native.log"), 0, 1);
    vc_require(!pc_command(1, 0, 0, 0), "physical-agent reset failed"); let actions = 0; let handoff = 0;
    while actions < nav_limit && !handoff {
        if vc_json_int(pc_state, "rgbDetections", 0) > 0 {
            let ack = pc_command(6, 0, 0, 0); if ack == 3 { handoff = 1; } else { vc_require(ack == 2, "physical handoff failed"); }
        }
        if !handoff {
            pc_record_input(); let action = ve_action(pc_hidden, 0); let steering = pb_read_float(action); let speed = pb_read_float(action + 4);
            vc_require(f64_is_finite(steering) && f64_is_finite(speed) && f64_le(f64_magnitude(steering), PB_ONE) && f64_le(f64_magnitude(speed), PB_ONE), "invalid visual-policy action");
            pc_record_action(action);
            vc_copy(ve_previous, action, 8); let s = f64_to_i64_nearest(f64_mul(steering, f64_from_i64(1000))); let v = f64_to_i64_nearest(f64_mul(speed, f64_from_i64(1000)));
            vc_require(pc_command(2, s, v, 10) == 1, "physical-agent drive failed"); actions = actions + 1;
        }
    }
    if pc_rescan_enabled && !handoff && actions == nav_limit { handoff = pc_stopped_rescan(); }
    let polls = 0; let terminal = 0;
    while handoff && polls < poll_limit && !terminal { let ack = pc_command(7, 0, 0, 20); vc_require(ack == 4 || ack == 5, "collector stopped with a protocol or time-limit failure");
        if ack == 5 { terminal = 1; pc_remember_terminal_failure(); } polls = polls + 1; }
    // A stopped or exhausted run remains a result to inspect, not a success.
    pc_stop();
    pc_check_inputs(simulator, model, case_path, environment); let trace_sha = vc_file_sha(vc_path(pc_output, "trace.jsonl")); pc_result(actions, handoff, terminal, nav_limit, poll_limit, trace_sha);
    syscall(3, pc_journal, 0, 0, 0, 0, 0); pl_print(1, "Hybrid run ended; inspect trace.jsonl with manipulation_audit.py.\n"); return 0;
}
