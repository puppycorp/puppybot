// Compile and atomically exec long-running native apps outside the source VM.
import "linux.flex";

fn pl_launcher_compiler(argc, argv, output) {
    let selected = pl_environment(argc, argv, "FLEXSCRIPT_COMPILER");
    if selected && load8(selected) { return selected; }
    let path = pl_environment(argc, argv, "PATH");
    if path {
        let at = 0; let size = pl_size(path);
        while at <= size {
            let end = at; while end < size && load8(path + end) != 58 { end = end + 1; }
            if end - at < 4000 {
                let b = pl_scratch + 512; pl_builder(b, output, 4096);
                if end == at { pl_text(b, "."); }
                else { let i = at; while i < end { pl_char(b, load8(path + i)); i = i + 1; } }
                pl_text(b, "/flexscript"); if syscall(21, output, 1, 0, 0, 0, 0) == 0 { return output; }
            }
            at = end + 1;
        }
    }
    if syscall(21, "../flexscript/build/flex", 1, 0, 0, 0, 0) == 0 { return "../flexscript/build/flex"; }
    return 0;
}
fn pl_launcher_directory(path) { let result = syscall(83, path, 493, 0, 0, 0, 0); return result == 0 || result == -17; }
fn pl_launcher_build(compiler, entry, temporary, environment) {
    let args = alloc(40); store64(args, compiler); store64(args + 8, entry);
    store64(args + 16, "-o"); store64(args + 24, temporary); store64(args + 32, 0);
    let pid = syscall(57, 0, 0, 0, 0, 0, 0);
    if pid < 0 { pl_print(2, "Puppybot: cannot start the native compiler.\n"); return 1; }
    if !pid {
        syscall(59, compiler, args, environment, 0, 0, 0);
        pl_print(2, "Puppybot: cannot execute FLEXSCRIPT_COMPILER.\n"); syscall(60, 127, 0, 0, 0, 0, 0); return 127;
    }
    let status = alloc(8); let result = syscall(61, pid, status, 0, 0, 0, 0);
    while result == -4 { result = syscall(61, pid, status, 0, 0, 0, 0); }
    if result != pid { return 1; }
    let code = load64(status); if code & 127 { return 128 + (code & 127); } return (code >> 8) & 255;
}
fn pl_native_launcher(argc, argv, entry, binary) {
    if !pl_init() { return 1; }
    if syscall(21, entry, 4, 0, 0, 0, 0) {
        pl_print(2, "Run Puppybot from the repository root, beside puppybot.json.\n"); return 2;
    }
    let compiler = pl_launcher_compiler(argc, argv, alloc(4096));
    if !compiler { pl_print(2, "Puppybot: install flexscript or set FLEXSCRIPT_COMPILER.\n"); return 1; }
    if !pl_launcher_directory("build") || !pl_launcher_directory("build/flex") { pl_print(2, "Puppybot: cannot create build/flex.\n"); return 1; }
    let temporary = alloc(256); let b = pl_scratch + 512; pl_builder(b, temporary, 256);
    pl_text(b, binary); pl_text(b, ".launch-"); pl_uint(b, syscall(39, 0, 0, 0, 0, 0, 0));
    let environment = argv + (argc + 1) * 8;
    let result = pl_launcher_build(compiler, entry, temporary, environment);
    if result { syscall(87, temporary, 0, 0, 0, 0, 0); pl_print(2, "Puppybot: native compilation failed; program was not started.\n"); return result; }
    if syscall(82, temporary, binary, 0, 0, 0, 0) { syscall(87, temporary, 0, 0, 0, 0, 0); pl_print(2, "Puppybot: cannot publish the native program.\n"); return 1; }
    let args = alloc((argc + 1) * 8); store64(args, binary); let i = 1;
    while i < argc { store64(args + i * 8, load64(argv + i * 8)); i = i + 1; } store64(args + argc * 8, 0);
    syscall(59, binary, args, environment, 0, 0, 0);
    pl_print(2, "Puppybot: cannot execute the native program.\n"); return 1;
}
