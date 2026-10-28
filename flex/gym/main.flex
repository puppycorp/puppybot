import "manager.flex";
import "views.flex";
import "native.flex";
extend "syntax.flex";
fn gg_options(argc, argv, options) {
    pb_zero(options, 128); pb_vset(options, 0, "arm-reach"); pb_vset(options, 1, 42); pb_vset(options, 3, "build/flex/puppybot-firmware-sim"); pb_vset(options, 4, 500);
    let i = 2;
    while i < argc {
        let arg = pb_vget(argv, i);
        if pl_equal(arg, "--realtime") { pb_vset(options, 5, 1); }
        else if pl_equal(arg, "--paused") { pb_vset(options, 6, 1); }
        else {
            if i + 1 >= argc { return 0; } let value = pb_vget(argv, i + 1); i = i + 1;
            if pl_equal(arg, "--case") { pb_vset(options, 0, value); pb_vset(options, 12, 1); }
            else if pl_equal(arg, "--case-file") { pb_vset(options, 9, value); }
            else if pl_equal(arg, "--environment") { pb_vset(options, 10, value); }
            else if pl_equal(arg, "--output") { pb_vset(options, 2, value); }
            else if pl_equal(arg, "--firmware") { pb_vset(options, 3, value); }
            else if pl_equal(arg, "--simulator") { pb_vset(options, 7, value); }
            else if pl_equal(arg, "--seed") || pl_equal(arg, "--steps") {
                let number = pl_integer(value, pl_size(value)); if pl_bad_number || number < 0 || number > 0xffffffff { return 0; }
                if pl_equal(arg, "--seed") { pb_vset(options, 1, number); }
                else { if number < 10 || number > 10000000 { return 0; } pb_vset(options, 4, number); pb_vset(options, 8, 1); }
            } else { return 0; }
        }
        i = i + 1;
    }
    if !pb_vget(options, 2) || !load8(pb_vget(options, 2)) || pl_size(pb_vget(options, 2)) > 3000 { return 0; }
    if pb_vget(options, 9) && pb_vget(options, 12) { return 0; }
    if pb_vget(options, 10) && !pb_vget(options, 9) && !gg_native_case(load64(options)) { return 0; }
    if gg_native_case(load64(options)) || pb_vget(options, 9) { if !pb_vget(options, 8) { pb_vset(options, 4, 750000); } }
    else if pb_vget(options, 4) > 10000 { return 0; }
    return gg_case_valid(load64(options));
}
fn gg_show(directory, replay) {
    let path = alloc(4096); let buffer = alloc(65537); gr_path(path, directory, "result.json");
    if !replay {
        let n = pl_read_file(path, buffer, 65536); if n == -2 { gr_path(path, directory, "progress.json"); n = pl_read_file(path, buffer, 65536); }
        if n < 0 { return 1; } pl_write(1, buffer, n); return 0;
    }
    gr_path(path, directory, "observations.jsonl"); let fd = syscall(2, path, 0x80000, 0, 0, 0, 0); if fd < 0 { return 1; }
    let active = 1; let result = 0;
    while active {
        let n = syscall(0, fd, buffer, 65536, 0, 0, 0);
        if n > 0 { if pl_write(1, buffer, n) { active = 0; result = 1; } }
        else if n != -4 { active = 0; if n < 0 { result = 1; } }
    }
    syscall(3, fd, 0, 0, 0, 0, 0); return result;
}
fn gg_usage() {
    return pl_print(1, "Usage: puppybotgym cases\n       puppybotgym serve [--bind IPv4:PORT] [--data DIRECTORY] [--firmware PATH] [--simulator PATH]\n           [--catalog-sim DIRECTORY] [--catalog-datasets DIRECTORY]\n           [--backend auto|sass|cuda|hip|cpu] [--device N]\n           [--model MANIFEST] [--vision BINARY] [--vision-kernel FILE]\n       puppybotgym detect --model MANIFEST --image IMAGE [detector options]\n       puppybotgym run --output NEW_DIRECTORY [--case CASE | --case-file FILE]\n           [--seed N] [--steps N] [--firmware PATH] [--simulator PATH]\n           [--environment apartment|FILE] [--realtime] [--paused]\n       puppybotgym show|replay DIRECTORY\n       puppybotgym pause|resume|stop DIRECTORY\n\nServo cases run native firmware against a servo plant. Scene cases run the\nnative camera/contact simulator, save video and maps, and default to maximum speed.\nNative arms use kinematic collision checks; articulated dynamics are not implemented.\n");
}
fn main(argc, argv) {
    if !pl_init() || !gx_init(argc, argv) { return 1; }
    if argc < 2 { gg_usage(); return 2; } let action = pb_vget(argv, 1);
    if pl_equal(action, "--help") || pl_equal(action, "-h") { gg_usage(); return 0; }
    if pl_equal(action, "cases") && argc == 2 {
        let b = alloc(32); let data = alloc(16384); pl_builder(b, data, 16384); gg_cases(b); pl_char(b, 10); pl_print(1, data); return load64(b + 24);
    }
    if (pl_equal(action, "show") || pl_equal(action, "replay")) && argc == 3 { return gg_show(pb_vget(argv, 2), pl_equal(action, "replay")); }
    if (pl_equal(action, "pause") || pl_equal(action, "resume") || pl_equal(action, "stop")) && argc == 3 {
        let path = alloc(4096); gr_path(path, pb_vget(argv, 2), "control"); if pl_atomic_file(path, action, pl_size(action)) { return 1; } return 0;
    }
    if pl_equal(action, "serve") { return gm_serve(argc, argv); }
    if pl_equal(action, "detect") { syscall(59, "build/flex/puppybot-vision", argv + 8, gx_env, 0, 0, 0); pl_print(2, "Cannot execute build/flex/puppybot-vision\n"); return 1; }
    if pl_equal(action, "run") || pl_equal(action, "worker") {
        if pl_equal(action, "worker") { syscall(3, 3, 0, 0, 0, 0, 0); }
        let options = alloc(128); if !gg_options(argc, argv, options) { gg_usage(); return 2; }
        if gg_native_case(load64(options)) || pb_vget(options, 9) {
            let result = gg_native_run(options); if gr_error { pl_print(2, "PuppyBotGym: "); pl_print(2, gr_error); pl_print(2, "\n"); } return result;
        }
        let result = gr_run(options); if gr_error { pl_print(2, "PuppyBotGym: "); pl_print(2, gr_error); pl_print(2, "\n"); } return result;
    }
    gg_usage(); return 2;
}
