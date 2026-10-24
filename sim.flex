// flexscript run sim.flex --case house-blocks-into-box --drift 10
// The small host entry point hands off to the native simulation build/run.
// Keep the long-running renderer outside the runner's VM execution budget.
fn sim_size(text) { let n = 0; while load8(text + n) { n = n + 1; } return n; }
fn sim_equal(a, b) {
    let i = 0; while load8(a + i) && load8(a + i) == load8(b + i) { i = i + 1; } return load8(a + i) == load8(b + i);
}
fn sim_error(message) { syscall(1, 2, message, sim_size(message), 0, 0, 0); return 1; }
fn main(argc, argv) {
    // argv[0] is the source filename in both runner invocation forms.
    let source = load64(argv); let slash = -1; let i = 0;
    while load8(source + i) { if load8(source + i) == 47 { slash = i; } i = i + 1; }
    if slash >= 0 {
        let directory = alloc(slash + 2); i = 0;
        while i < slash { store8(directory + i, load8(source + i)); i = i + 1; }
        if !slash { store8(directory, 47); i = 1; } store8(directory + i, 0);
        if syscall(80, directory, 0, 0, 0, 0, 0) { return sim_error("Cannot open the simulation project directory.\n"); }
    }
    let selected = 0; i = 1;
    while i < argc {
        let arg = load64(argv + i * 8);
        if sim_equal(arg, "--case") || sim_equal(arg, "--demo") || sim_equal(arg, "--pickup") || sim_equal(arg, "--pickup-release") || sim_equal(arg, "--vision-pickup") || sim_equal(arg, "--vision-pickup-release") || sim_equal(arg, "--stock-landmarks") || sim_equal(arg, "--stock-pickup") || sim_equal(arg, "--landmark-output") { selected = 1; }
        i = i + 1;
    }
    let args = alloc((argc + 7) * 8); store64(args, "/bin/bash"); store64(args + 8, "flex/scripts/run-sim.sh");
    store64(args + 16, "--bind"); store64(args + 24, "127.0.0.1:0"); let count = 4;
    if !selected { store64(args + count * 8, "--case"); store64(args + (count + 1) * 8, "house-blocks-into-box"); count = count + 2; }
    i = 1; while i < argc { store64(args + count * 8, load64(argv + i * 8)); count = count + 1; i = i + 1; } store64(args + count * 8, 0);
    syscall(59, "/bin/bash", args, argv + (argc + 1) * 8, 0, 0, 0);
    return sim_error("Cannot start the native simulation build/run helper.\n");
}
