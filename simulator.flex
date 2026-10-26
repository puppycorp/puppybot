// 3D environment with a private serial bus; the controller runs independently.
// --servo-only retains the lightweight encoder/velocity simulator.
import "flex/host/launcher.flex";
fn main(argc, argv) {
    let lightweight = 0; let i = 1;
    while i < argc { if pl_equal(load64(argv + i * 8), "--servo-only") { lightweight = 1; } i = i + 1; }
    if lightweight {
        let args = alloc((argc + 1) * 8); store64(args, load64(argv)); let count = 1; i = 1;
        while i < argc { let arg = load64(argv + i * 8); if !pl_equal(arg, "--servo-only") { store64(args + count * 8, arg); count = count + 1; } i = i + 1; }
        // Preserve execve's environment layout after removing a launcher option.
        let environment = argv + (argc + 1) * 8; let n = 0; while load64(environment + n * 8) { n = n + 1; }
        let combined = alloc((count + n + 2) * 8); pb_copy(combined, args, count * 8); store64(combined + count * 8, 0);
        pb_copy(combined + (count + 1) * 8, environment, (n + 1) * 8);
        return pl_native_launcher(count, combined, "flex/simulator/main.flex", "build/flex/puppybot-simulator");
    }
    let args = alloc((argc + 7) * 8); store64(args, "/bin/bash"); store64(args + 8, "flex/scripts/run-sim.sh");
    store64(args + 16, "--external-serial"); store64(args + 24, "--bind"); store64(args + 32, "127.0.0.1:0");
    let count = 5; i = 1;
    while i < argc { store64(args + count * 8, load64(argv + i * 8)); count = count + 1; i = i + 1; } store64(args + count * 8, 0);
    syscall(59, "/bin/bash", args, argv + (argc + 1) * 8, 0, 0, 0);
    pl_print(2, "Cannot start the native simulator build/run helper.\n"); return 1;
}
