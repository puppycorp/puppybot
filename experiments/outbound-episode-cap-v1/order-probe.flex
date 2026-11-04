// CPU-only exercise of the actual trainer's row checks, fitting permutation,
// map loader and both batch loops with 1,029 one-step histories.
fn main(argc, argv) {
    vc_init(argc, argv); if argc != 2 { return 2; }
    let episodes = 1029; let training_count = 933; let length = 1;
    pt_length = length; pt_batch = 2; pt_image_bytes = 21168; pt_row_bytes = 56;
    pt_record_size = pt_length * (pt_image_bytes + pt_row_bytes);
    let size = 32 + episodes * pt_record_size; pt_data = alloc(size); pb_zero(pt_data, size);
    vc_copy(pt_data, "PVDATA04", 8); store64(pt_data + 8, episodes);
    store64(pt_data + 16, training_count); store64(pt_data + 24, length);
    let i = 0;
    while i < episodes {
        let base = pt_data + 32 + i * pt_record_size; store8(base, i % 251);
        let row = base + pt_image_bytes;
        pb_put32(row + 28, 0x3f000000); pb_put32(row + 32, 0xbf000000);
        pb_put32(row + 40, 0x3f800000); pb_put32(row + 44, 0x3f800000);
        pb_put32(row + 48, 0x3f000000); pb_put32(row + 52, 0xbf000000);
        i = i + 1;
    }
    if vd_episode_limit(pt_data) != 1030 { return 10; }
    pt_check_rows(episodes);
    pt_map_aux = 1; pt_map_open(load64(argv + 8), pt_data);
    let order = alloc(episodes * 8); let seen = alloc(training_count); pb_zero(seen, training_count);
    i = 0; while i < episodes { store64(order + i * 8, i); i = i + 1; }
    pt_rng = 7;
    @@TRAINING_SHUFFLE@@
    i = 0; while i < training_count {
        let episode = load64(order + i * 8);
        if episode < 0 || episode >= training_count || load8(seen + episode) { return 11; }
        store8(seen + episode, 1); i = i + 1;
    }
    i = training_count; while i < episodes { if load64(order + i * 8) != i { return 12; } i = i + 1; }
    pt_batch_images = alloc(pt_batch * pt_image_bytes); pt_batch_proprio = alloc(pt_batch * 28);
    pt_batch_targets = alloc(pt_batch * 16); pt_batch_phase_masks = alloc(pt_batch * 4);
    pt_batch_map = alloc(pt_batch * 144); pt_memcpy = ffi_symbol(ffi_open("libc.so.6"), "memcpy");
    if !pt_memcpy { return 13; }
    let split = 0; let fitting_samples = 0; let validation_samples = 0; let partial_batches = 0;
    while split < 2 {
        let start = 0; let end = training_count; if split { start = training_count; end = episodes; }
        while start < end {
            let count = pb_min(pt_batch, end - start); if count < pt_batch { partial_batches = partial_batches + 1; }
            pt_batch_fill(order, start, count); let b = 0;
            while b < count {
                let episode = load64(order + (start + b) * 8);
                if load8(pt_batch_images + b * pt_image_bytes) != (episode % 251) ||
                   load8(pt_batch_map + b * 144) != (episode % 3) ||
                   pb_u32(pt_batch_targets + b * 16 + 12) != 0x3f800000 { return 17; }
                if split { validation_samples = validation_samples + 1; } else { fitting_samples = fitting_samples + 1; }
                b = b + 1;
            }
            if count < pt_batch && (pb_u32(pt_batch_targets + count * 16 + 12) ||
                                    load8(pt_batch_map + count * 144) != 2) { return 18; }
            start = start + pt_batch;
        }
        split = split + 1;
    }
    if fitting_samples != 933 || validation_samples != 96 || partial_batches != 1 { return 19; }
    // Also exercise an independently requested last-index partial batch.
    pt_batch_fill(order, 1028, 1);
    if load8(pt_batch_images) != (1028 % 251) || load8(pt_batch_map) != (1028 % 3) ||
       pb_u32(pt_batch_targets + 12) != 0x3f800000 || pb_u32(pt_batch_targets + 28) ||
       load8(pt_batch_map + 144) != 2 || load8(pt_batch_map + 287) != 2 { return 14; }
    // Locate and load the first newly inserted fitting episode after shuffling.
    let location = 0; while location < training_count && load64(order + location * 8) != 928 { location = location + 1; }
    if location == training_count { return 15; }
    pt_batch_fill(order, location, 1);
    if load8(pt_batch_images) != (928 % 251) || load8(pt_batch_map) != (928 % 3) { return 16; }
    pl_print(1, "1029-history fitting permutation and validation batch passed\n"); return 0;
}
