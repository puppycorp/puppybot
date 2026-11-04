// Bounded local message transport. Only protocol bytes cross the process boundary.
import "../host/linux.flex";

global gx_rx = 0;
global gx_tx = 0;
global gx_kind = 0;
global gx_size = 0;
global gx_env = 0;

fn gx_init(argc, argv) {
    gx_rx = alloc(4120); gx_tx = alloc(4120); gx_env = argv + (argc + 1) * 8;
    return gx_rx > 0 && gx_tx > 0;
}
fn gx_send(fd, kind, data, size) {
    if size < 0 || size > 4096 { return 0; }
    store64(gx_tx, 0x314d5947544f4250); store64(gx_tx + 8, kind); store64(gx_tx + 16, size); pb_copy(gx_tx + 24, data, size);
    let deadline = pl_now() + 2000;
    while 1 {
        let n = syscall(44, fd, gx_tx, size + 24, 16384, 0, 0);
        if n == size + 24 { return 1; }
        if n == -11 { if !pl_wait(fd, 4, deadline) { return 0; } } else if n != -4 { return 0; }
    }
    return 0;
}
fn gx_receive(fd, timeout) {
    let deadline = pl_now() + timeout;
    while 1 {
        let n = syscall(45, fd, gx_rx, 4120, 32, 0, 0);
        if n > 0 {
            if n < 24 || n > 4120 || load64(gx_rx) != 0x314d5947544f4250 || load64(gx_rx + 16) != n - 24 { return -1; }
            gx_kind = load64(gx_rx + 8); gx_size = n - 24; return 1;
        }
        if !n { return -1; }
        if n == -11 { if !timeout || !pl_wait(fd, 1, deadline) { return 0; } } else if n != -4 { return -1; }
    }
    return -1;
}
// Return child PID and parent socket in result[2]. Child receives only fd 3.
fn gx_spawn(binary, args, log_path, result) {
    let pair = pl_scratch + 256;
    if syscall(53, 1, 0x80805, 0, pair, 0, 0) { return 0; }
    let parent = pb_u32(pair); let child = pb_u32(pair + 4); let owner = syscall(39, 0, 0, 0, 0, 0, 0);
    let log = syscall(2, log_path, 0x800c1, 384, 0, 0, 0);
    if log < 0 { syscall(3, parent, 0, 0, 0, 0, 0); syscall(3, child, 0, 0, 0, 0, 0); return 0; }
    let pid = syscall(57, 0, 0, 0, 0, 0, 0);
    if !pid {
        syscall(157, 1, 9, 0, 0, 0, 0);
        if syscall(110, 0, 0, 0, 0, 0, 0) != owner { syscall(60, 125, 0, 0, 0, 0, 0); }
        syscall(33, log, 1, 0, 0, 0, 0); syscall(33, log, 2, 0, 0, 0, 0);
        syscall(33, child, 3, 0, 0, 0, 0); syscall(72, 3, 2, 0, 0, 0, 0);
        syscall(436, 4, 0xffffffff, 0, 0, 0, 0);
        syscall(59, binary, args, gx_env, 0, 0, 0); syscall(60, 127, 0, 0, 0, 0, 0);
    }
    syscall(3, log, 0, 0, 0, 0, 0); syscall(3, child, 0, 0, 0, 0, 0);
    if pid < 0 { syscall(3, parent, 0, 0, 0, 0, 0); return 0; }
    store64(result, pid); store64(result + 8, parent); return 1;
}
fn gx_reap(pid, timeout) {
    let deadline = pl_now() + timeout; let status = pl_scratch + 256;
    while 1 {
        let n = syscall(61, pid, status, 1, 0, 0, 0);
        if n == pid { return pb_u32(status); }
        if n < 0 && n != -4 { return -1; }
        if pl_now() >= deadline { return -2; }
        syscall(7, 0, 0, 2, 0, 0, 0);
    }
    return -1;
}
fn gx_finish(pid, fd) {
    syscall(3, fd, 0, 0, 0, 0, 0); let status = gx_reap(pid, 1000);
    if status == -2 { syscall(62, pid, 9, 0, 0, 0, 0); status = gx_reap(pid, 1000); }
    return status;
}
