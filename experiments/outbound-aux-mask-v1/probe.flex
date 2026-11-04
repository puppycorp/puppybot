// Host-only test of batch masks and output seeds; no device graph is run.
fn main(argc, argv) {
    vc_init(argc, argv);
    pt_length = 4; pt_batch = 1; pt_image_bytes = 4; pt_row_bytes = 56;
    pt_record_size = pt_length * (pt_image_bytes + pt_row_bytes);
    let episodes = 3; pt_data = alloc(32 + episodes * pt_record_size);
    pb_zero(pt_data, 32 + episodes * pt_record_size);
    let e = 0;
    while e < episodes {
        let base = pt_data + 32 + e * pt_record_size; let t = 0;
        while t < pt_length {
            store8(base + t * pt_image_bytes, 10 + e * 4 + t);
            let row = base + pt_length * pt_image_bytes + t * pt_row_bytes;
            pb_put32(row, 0x3f000000); pb_put32(row + 28, 0x3f000000); pb_put32(row + 32, 0x3f800000);
            if t >= 2 { pb_put32(row + 36, 0x3f800000); } else { pb_put32(row + 40, 0x3f800000); }
            pb_put32(row + 44, 0x3f800000); t = t + 1;
        }
        e = e + 1;
    }
    pt_check_rows(episodes);
    let order = alloc(24); e = 0; while e < episodes { store64(order + e * 8, e); e = e + 1; }
    pt_memcpy = ffi_symbol(ffi_open("libc.so.6"), "memcpy"); if !pt_memcpy { return 3; }
    pt_batch_images = alloc(16); pt_batch_proprio = alloc(4 * 28); pt_batch_targets = alloc(4 * 16);
    pt_batch_phase_masks = alloc(4 * 4); pt_phase_from_valid = 1;
    pt_action_width = 2; pt_prediction = alloc(4 * 2 * 4); pt_phase_prediction = alloc(4 * 4);
    pt_action_seed = alloc(4 * 2 * 4); pt_phase_seed = alloc(4 * 4);
    pt_event_aux = 1; pt_event_prediction = alloc(4 * 4); pt_event_seed = alloc(4 * 4);
    pt_pose_aux = 1; pt_pose_data = alloc(32 + episodes * 4 * 20);
    pt_batch_pose = alloc(4 * 20); pt_pose_prediction = alloc(4 * 16); pt_pose_seed = alloc(4 * 16);
    pt_map_aux = 1; pt_map_data = alloc(32 + episodes * 4 * 144);
    pt_batch_map = alloc(4 * 144); pt_map_prediction = alloc(4 * 144 * 4); pt_map_seed = alloc(4 * 144 * 4);
    pt_target_aux = 1; pt_target_data = alloc(32 + episodes * 4 * 12); pt_batch_target_positions = alloc(4 * 12);
    pt_target_prediction = alloc(4 * 400 * 4); pt_target_seed = alloc(4 * 400 * 4);
    e = 0; while e < episodes * 4 {
        pb_put32(pt_pose_data + 32 + e * 20, 0x3f800000); pb_put32(pt_pose_data + 32 + e * 20 + 16, 0x3f800000);
        let c = 0; while c < 144 { store8(pt_map_data + 32 + e * 144 + c, 2); c = c + 1; }
        store8(pt_map_data + 32 + e * 144, 1);
        pb_put32(pt_target_data + 32 + e * 12, 0x3f000000); pb_put32(pt_target_data + 32 + e * 12 + 8, 0x3f800000);
        e = e + 1;
    }
    // All episodes contain the same supervision pattern. Only episode 1 is
    // in the staged outbound range; 0 and 2 represent preserved baselines.
    e = 0; while e < episodes {
        pt_batch_fill(order, e, 1); let t = 0;
        while t < 4 {
            if load8(pt_batch_images + t * 4) != 10 + e * 4 + t || pb_u32(pt_batch_proprio + t * 28) != 0x3f000000 { return 10; }
            let masked = e == 1 && t >= 2;
            if masked {
                if pb_u32(pt_batch_phase_masks + t * 4) || pb_u32(pt_batch_pose + t * 20 + 16) ||
                   pb_u32(pt_batch_target_positions + t * 12 + 8) || load8(pt_batch_map + t * 144) != 2 { return 11; }
            } else {
                if pb_u32(pt_batch_phase_masks + t * 4) != 0x3f800000 || pb_u32(pt_batch_pose + t * 20 + 16) != 0x3f800000 ||
                   pb_u32(pt_batch_target_positions + t * 12 + 8) != 0x3f800000 || load8(pt_batch_map + t * 144) != 1 { return 12; }
            }
            t = t + 1;
        }
        pt_loss_host(1, 0);
        if e == 1 {
            if f64_magnitude(pb_read_float(pt_phase_seed + 8)) || f64_magnitude(pb_read_float(pt_pose_seed + 2 * 16)) ||
               f64_magnitude(pb_read_float(pt_target_seed + 2 * 8)) || f64_magnitude(pb_read_float(pt_map_seed + 2 * 576)) ||
               f64_magnitude(pb_read_float(pt_event_seed + 8)) || f64_magnitude(pb_read_float(pt_event_seed + 12)) { return 13; }
            if !f64_magnitude(pb_read_float(pt_phase_seed)) || !f64_magnitude(pb_read_float(pt_pose_seed)) ||
               !f64_magnitude(pb_read_float(pt_target_seed)) || !f64_magnitude(pb_read_float(pt_map_seed)) ||
               !f64_magnitude(pb_read_float(pt_event_seed)) || !f64_magnitude(pb_read_float(pt_event_seed + 4)) { return 14; }
            if !pt_reversal_pair(pt_batch_targets, pt_batch_targets + 16) ||
               pt_reversal_pair(pt_batch_targets + 16, pt_batch_targets + 32) ||
               !pt_phase_consistency_pair(pt_batch_targets, pt_batch_targets + 16, pt_batch_phase_masks, pt_batch_phase_masks + 4) ||
               pt_phase_consistency_pair(pt_batch_targets + 16, pt_batch_targets + 32, pt_batch_phase_masks + 4, pt_batch_phase_masks + 8) { return 20; }
        } else {
            if !f64_magnitude(pb_read_float(pt_phase_seed + 8)) || !f64_magnitude(pb_read_float(pt_pose_seed + 2 * 16)) ||
               !f64_magnitude(pb_read_float(pt_target_seed + 2 * 8)) || !f64_magnitude(pb_read_float(pt_map_seed + 2 * 576)) { return 15; }
        }
        e = e + 1;
    }
    // Heat-absence code can assign an extra -1 mask on a return suffix;
    // ensure the later selected-episode override clears that as well.
    pt_target_aux = 0; pt_heat_aux = 1; pt_heat_absence = 1; pt_target_width = 400;
    pt_batch_fill(order, 1, 1);
    if pb_u32(pt_batch_target_positions + 3 * 12 + 8) { return 16; }
    pt_batch_fill(order, 0, 1);
    if pb_u32(pt_batch_target_positions + 3 * 12 + 8) != 0xbf800000 { return 17; }
    pl_print(1, "outbound auxiliary batch and host-loss masks passed\n"); return 0;
}
