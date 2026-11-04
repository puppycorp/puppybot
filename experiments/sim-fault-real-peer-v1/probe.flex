// A deterministic protocol client for the simulator-only fault diagnostic.
// It exercises real environment code, not the learned policy or vx_episode.
import "environment.flex";

fn main(argc, argv) {
    vc_init(argc, argv); vc_require(argc == 5, "expected socket, simulator pid, output and mode");
    let fd = pl_integer(load64(argv + 8), pl_size(load64(argv + 8)));
    let pid = pl_integer(load64(argv + 16), pl_size(load64(argv + 16)));
    let directory = load64(argv + 24); let mode = load64(argv + 32);
    vc_require(pl_equal(mode, "control") || pl_equal(mode, "fault"), "invalid probe mode");
    vc_require(fd >= 0 && pid > 0, "invalid peer");
    ve_open_buffers(); ve_process = alloc(16); store64(ve_process, pid); store64(ve_process + 8, fd);
    vc_require(!syscall(72, fd, 4, 2048, 0, 0, 0), "cannot make peer nonblocking");
    ve_lean = 1; ve_task = 3; ve_sequence = 0; ve_directory = directory;
    ve_journal = syscall(2, vc_path(directory, "decisions.jsonl"), 0x800c1, 384, 0, 0, 0);
    vc_require(ve_journal >= 0, "cannot create journal");
    vc_fault_stop_enabled = 1; vc_fault_stop_fd = fd; vc_fault_stop_pid = pid;
    vc_fault_stop_sequence = 0; vc_fault_stop_attempted = 0; vc_fault_stop_ready = 0;
    pb_zero(ve_previous, 8); ve_command(1, 0, 0); ve_check(1);
    ve_pose_read(ve_state, ve_pose); vc_copy(ve_initial_pose, ve_pose, 24);
    vc_fault_stop_ready = 1;
    let action = alloc(8); pb_put32(action, 0); pb_put32(action + 4, 0x3f000000);
    ve_step(action); ve_step(action);
    // The fault arm should terminate in the second ve_step. If it reaches
    // here, close normally and fail the diagnostic rather than claim a stop.
    vc_fault_stop_fd = -1; ve_command(3, 0, 0);
    vc_require(pl_equal(mode, "control"), "fault was not detected"); return 0;
}
