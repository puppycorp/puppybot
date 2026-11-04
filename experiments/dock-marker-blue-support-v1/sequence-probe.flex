// Saved frames are independently read and passed through one detector state.
// This does not render or prove that a physical camera produced fresh images.
fn main(argc, argv) {
    if !pl_init() || argc != 7 { return 1; }
    ps_dock_small_components = 1; ps_case_camera = 2; ps_case_bin = alloc(64);
    store64(ps_case_bin + 24, ps_number(22, 100)); store64(ps_case_bin + 32, ps_number(20, 100));
    store64(ps_case_bin + 40, ps_number(9, 100)); store64(ps_case_bin + 48, ps_number(8, 1000));
    ps_brick_rgb = alloc(640 * 480 * 3 + 1); ps_brick_mask = alloc(640 * 480);
    ps_brick_queue = alloc(640 * 480 * 8); ps_brick_pose = alloc(97);
    if pl_read_file(load64(argv + 48), ps_brick_pose, 96) != 96 { return 3; }
    ps_dock_reset(); let i = 0; let text = alloc(2048); let b = alloc(32); pl_builder(b, text, 2048); pl_char(b, 91);
    while i < 5 {
        if pl_read_file(load64(argv + (i + 1) * 8), ps_brick_rgb, 640 * 480 * 3) != 640 * 480 * 3 { return 2; }
        ps_total = 11477 + 10 * i; let found = ps_dock_detect(); ps_dock_attention(found);
        if i { pl_char(b, 44); } pl_text(b, "{\"found\":"); pl_int(b, found);
        pl_text(b, ",\"stable\":"); pl_int(b, ps_dock_stable); pl_text(b, ",\"position\":[");
        pl_float(b, load64(ps_dock_frame + 96)); pl_char(b, 44); pl_float(b, load64(ps_dock_frame + 104)); pl_text(b, "]}");
        i = i + 1;
    } pl_text(b, "]\n"); pl_write(1, text, load64(b + 8)); return 0;
}
