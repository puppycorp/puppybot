// Frozen YOLO backbone features, without detection decoding or robot state.
import "../vision/image.flex";
import "../../build/flex/yolo-encoder-model.flex";

fn ye_setup(manifest, kernel, backend) {
    vp_init(kernel, backend, 0); let data = alloc(65537); let size = pl_read_file(manifest, data, 65536);
    vp_require(size > 0, "cannot read encoder manifest"); let root = pj_parse(data, size);
    vp_require(pl_equal(pj_string_field(root, "schema"), "puppybot.encoder.v1") && !pj_error, "invalid encoder schema");
    vp_require(pl_equal(pj_string_field(root, "modelSha256"), pup_model_source_hash()) && !pj_error, "encoder graph hash mismatch");
    let weights = pj_string_field(root, "weights"); let hash = pj_string_field(root, "weightsSha256");
    vp_require(!pj_error, "missing encoder checkpoint"); vp_checkpoint_open(weights, hash); pup_build_model();
    vp_require(load64(vp_inputs) == 1 && load64(vp_outputs) == 1, "encoder requires one input and output");
    vp_require(vp_rank(vp_output) == 4 && vp_dim(vp_output, 0) == 1 && vp_dim(vp_output, 1) == 128 && vp_dim(vp_output, 2) == vp_dim(vp_input, 2) / 16 && vp_dim(vp_output, 3) == vp_dim(vp_input, 3) / 16, "unexpected encoder tensor shape");
    return 0;
}
fn ye_report() {
    let b = alloc(32); let text = alloc(256); pl_builder(b, text, 256);
    pl_text(b, "{\"schema\":\"puppybot.encoder-result.v1\",\"shape\":[1,128,"); pl_uint(b, vp_dim(vp_output, 2)); pl_char(b, 44); pl_uint(b, vp_dim(vp_output, 3));
    pl_text(b, "],\"backend\":\""); pl_text(b, vp_backend_name()); pl_text(b, "\"}");
    syscall(11, b, 32, 0, 0, 0, 0); return text;
}
fn ye_encode(input, output) {
    let rgb = alloc(640 * 480 * 3 + 1); vp_require(pl_read_file(input, rgb, 640 * 480 * 3 + 1) == 640 * 480 * 3, "encoder requires exact 640x480 RGB bytes");
    let tensor = vi_preprocess(rgb, 640, 480); vp_upload(load64(vp_input), tensor, load64(vp_input + 8) * 4);
    vp_execute(); let bytes = load64(vp_output + 8) * 4; let result = alloc(bytes); vp_read_output(result);
    vp_require(!pl_atomic_file(output, result, bytes), "cannot save encoder features");
    syscall(11, rgb, 640 * 480 * 3 + 1, 0, 0, 0, 0); syscall(11, tensor, load64(vp_input + 8) * 4, 0, 0, 0, 0); syscall(11, result, bytes, 0, 0, 0, 0); return 0;
}
fn ye_worker(fd) {
    let reply = ye_report(); let packet = alloc(8193);
    vp_require(syscall(44, fd, reply, pl_size(reply), 16384, 0, 0) == pl_size(reply), "cannot announce encoder readiness");
    while 1 {
        let size = syscall(45, fd, packet, 8192, 32, 0, 0); if !size { return 0; }
        vp_require(size > 2 && size < 8192, "invalid encoder request"); store8(packet + size, 0);
        let second = packet + pl_size(packet) + 1;
        vp_require(second < packet + size && pl_size(second) + (second - packet) + 1 == size, "invalid encoder path packet");
        ye_encode(packet, second); vp_require(syscall(44, fd, reply, pl_size(reply), 16384, 0, 0) == pl_size(reply), "cannot reply to encoder client");
    } return 0;
}
fn main(argc, argv) {
    if !pl_init() { return 1; } let manifest = 0; let input = 0; let output = 0; let kernel = 0; let backend = -1; let worker = -1;
    let i = 1;
    while i < argc {
        if i + 1 >= argc { return 2; } let key = load64(argv + i * 8); let value = load64(argv + (i + 1) * 8);
        if pl_equal(key, "--model") { manifest = value; } else if pl_equal(key, "--rgb") { input = value; }
        else if pl_equal(key, "--output") { output = value; } else if pl_equal(key, "--kernel") { kernel = value; }
        else if pl_equal(key, "--backend") { backend = vp_backend_parse(value); if backend == -2 { return 2; } }
        else if pl_equal(key, "--worker-fd") { worker = pl_integer(value, pl_size(value)); if pl_bad_number || worker < 3 { return 2; } }
        else { return 2; } i = i + 2;
    }
    if !manifest || !kernel || (worker < 0 && (!input || !output)) { return 2; } ye_setup(manifest, kernel, backend);
    if worker >= 0 { return ye_worker(worker); } ye_encode(input, output); pl_print(1, ye_report()); pl_print(1, "\n"); return 0;
}
