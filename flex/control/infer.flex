// Resident deterministic CNN/GRU policy inference through the native Pup runtime.
// The client supplies image, own-state and hidden-state FP32 tensors in order.
import "../ml/runtime.flex";
import "../../build/flex/pixel-control-model.flex";

fn pc_read(fd, data, size) {
    let offset = 0;
    while offset < size { let n = syscall(0, fd, data + offset, size - offset, 0, 0, 0); if n <= 0 { return 0; } offset = offset + n; }
    return 1;
}
fn main(argc, argv) {
    if !pl_init() || argc != 5 { return 2; }
    let fd = pl_integer(load64(argv + 32), pl_size(load64(argv + 32))); if pl_bad_number || fd < 3 { return 2; }
    vp_init(load64(argv + 24), vp_backend_parse("cuda"), 0);
    vp_checkpoint_open(load64(argv + 8), load64(argv + 16)); pup_build_model(); vp_check(device_synchronize());
    vp_require(load64(vp_inputs) == 3 && load64(vp_outputs) == 2, "visual policy requires three inputs and two outputs");
    let input_size = 0; let output_size = 0; let i = 0;
    while i < 3 { input_size = input_size + load64(vp_at(vp_at(vp_inputs, i), 1) + 8) * 4; i = i + 1; }
    i = 0; while i < 2 { output_size = output_size + load64(vp_at(vp_outputs, i) + 8) * 4; i = i + 1; }
    vp_require(input_size == (3 * 84 * 84 + 7 + 128) * 4 && output_size == 130 * 4, "unexpected policy tensor dimensions");
    let input = alloc(input_size); let output = alloc(output_size);
    vp_require(!pl_write(fd, "VCPOL001", 8), "cannot announce visual policy");
    while pc_read(fd, input, input_size) {
        let offset = 0; i = 0;
        while i < 3 { let tensor = vp_at(vp_at(vp_inputs, i), 1); let size = load64(tensor + 8) * 4; vp_check(device_upload_async(load64(tensor), input + offset, size, vp_stream)); offset = offset + size; i = i + 1; }
        vp_execute(); offset = 0; i = 0;
        while i < 2 { let tensor = vp_at(vp_outputs, i); vp_read_tensor(tensor, output + offset); offset = offset + load64(tensor + 8) * 4; i = i + 1; }
        if pl_write(fd, output, output_size) { return 1; }
    }
    return 0;
}
