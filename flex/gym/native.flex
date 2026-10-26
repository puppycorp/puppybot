// Hand native scenes to the simulator process; Gym retains lifecycle/catalog ownership.
import "cases.flex";

fn gg_absolute(path) {
    if load8(path) == 47 { return path; } let cwd = alloc(4096);
    if syscall(79, cwd, 4096, 0, 0, 0, 0) < 0 { return 0; } return h_cat3(cwd, "/", path);
}
fn gg_native_run(options) {
    let output = gg_absolute(pb_vget(options, 2)); let launcher = pb_vget(options, 7);
    if !launcher { launcher = h_cat(gg_project_root(), "/flex/scripts/run-sim.sh"); } else { launcher = gg_absolute(launcher); }
    if !output || !launcher || syscall(21, launcher, 1, 0, 0, 0, 0) { gr_fail("native simulator launcher is missing"); return 2; }
    let selector = "--case"; let name = load64(options);
    if pb_vget(options, 9) { selector = "--case-file"; name = gg_absolute(pb_vget(options, 9)); }
    let args = h_args(launcher, selector, name, "--hidden", "--steps", h_int(pb_vget(options, 4)));
    h_add(args, "--gym-output"); h_add(args, output); h_add(args, "--seed"); h_add(args, h_int(pb_vget(options, 1))); h_add(args, "--bind"); h_add(args, "127.0.0.1:0");
    h_add(args, "--tcp-view");
    if pb_vget(options, 10) {
        let environment = pb_vget(options, 10); if !pl_equal(environment, "apartment") { environment = gg_absolute(environment); }
        h_add(args, "--environment"); h_add(args, environment);
    }
    if pb_vget(options, 5) { h_add(args, "--realtime"); } if pb_vget(options, 6) { h_add(args, "--paused"); }
    store64(args + 8 + h_count(args) * 8, 0);
    if syscall(80, gg_project_root(), 0, 0, 0, 0, 0) { return 2; }
    syscall(59, launcher, args + 8, gx_env, 0, 0, 0); gr_fail("cannot execute native simulator"); return 2;
}
