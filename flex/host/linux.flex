// Linux x86-64 process, file and socket adapter. Buffers are retained/reused.
import "numbers.flex";

global pl_clock = 0;
global pl_scratch = 0;
global pl_paths = 0;
global pl_bad_number = 0;
global pl_signal = -1;
global pl_libc = 0;
global pl_resolve = 0;
global pl_free_addresses = 0;

fn pl_init() {
    if pl_clock { return 1; }
    pl_clock = alloc(16); pl_scratch = alloc(1024); pl_paths = alloc(8192);
    return pl_clock > 0 && pl_scratch > 0 && pl_paths > 0 && pn_init();
}
fn pl_now() {
    if syscall(228, 1, pl_clock, 0, 0, 0, 0) < 0 { return -1; }
    return load64(pl_clock) * 1000 + load64(pl_clock + 8) / 1000000;
}
fn pl_size(text) { let n = 0; while load8(text + n) { n = n + 1; } return n; }
fn pl_equal(a, b) {
    let i = 0; while load8(a + i) && load8(a + i) == load8(b + i) { i = i + 1; }
    return load8(a + i) == load8(b + i);
}
fn pl_starts(text, prefix) {
    let i = 0; while load8(prefix + i) { if load8(prefix + i) != load8(text + i) { return 0; } i = i + 1; } return 1;
}
fn pl_ascii_lower(c) { if c >= 65 && c <= 90 { return c + 32; } return c; }
fn pl_case_equal(a, an, b) {
    let i = 0; while i < an { if pl_ascii_lower(load8(a + i)) != pl_ascii_lower(load8(b + i)) { return 0; } i = i + 1; }
    return load8(b + an) == 0;
}
fn pl_environment(argc, argv, name) {
    let at = argv + (argc + 1) * 8; let size = pl_size(name);
    while load64(at) {
        let value = load64(at); let i = 0;
        while i < size && load8(value + i) == load8(name + i) { i = i + 1; }
        if i == size && load8(value + i) == 61 { return value + i + 1; } at = at + 8;
    }
    return 0;
}
fn pl_unsigned_less(a, b) { return (a ^ 0x8000000000000000) < (b ^ 0x8000000000000000); }
fn pl_unsigned_parse(text, size) {
    pl_bad_number = 0; let value = 0; let i = 0;
    if size < 1 { pl_bad_number = 1; return 0; }
    while i < size {
        let digit = load8(text + i) - 48;
        if digit < 0 || digit > 9 || pl_unsigned_less(1844674407370955161, value) || (value == 1844674407370955161 && digit > 5) { pl_bad_number = 1; return 0; }
        value = value * 10 + digit; i = i + 1;
    }
    return value;
}
fn pl_integer(text, size) {
    let negative = 0;
    if size && load8(text) == 45 { negative = 1; text = text + 1; size = size - 1; }
    let value = pl_unsigned_parse(text, size); if pl_bad_number { return 0; }
    if (!negative && value < 0) || (negative && pl_unsigned_less(0x8000000000000000, value)) { pl_bad_number = 1; return 0; }
    if negative { return -value; } return value;
}
fn pl_write(fd, bytes, size) {
    let at = 0;
    while at < size {
        let n = syscall(1, fd, bytes + at, size - at, 0, 0, 0);
        if n > 0 { at = at + n; } else if n != -4 { return -1; }
    }
    return 0;
}
fn pl_print(fd, text) { return pl_write(fd, text, pl_size(text)); }
fn pl_builder(builder, bytes, capacity) {
    store64(builder, bytes); store64(builder + 8, 0); store64(builder + 16, capacity); store64(builder + 24, 0);
    if capacity > 0 { store8(bytes, 0); } return builder;
}
fn pl_append(builder, source, size) {
    let used = load64(builder + 8); let capacity = load64(builder + 16);
    if size < 0 || size >= capacity - used || load64(builder + 24) { store64(builder + 24, 1); return -1; }
    let out = load64(builder); pb_copy(out + used, source, size); store8(out + used + size, 0);
    store64(builder + 8, used + size); return 0;
}
fn pl_text(builder, text) { return pl_append(builder, text, pl_size(text)); }
fn pl_char(builder, byte) { store8(pl_scratch + 128, byte); return pl_append(builder, pl_scratch + 128, 1); }
fn pl_udiv10(value) {
    if value >= 0 { return value / 10; }
    let low = value & 0x7fffffffffffffff;
    return low / 10 + 922337203685477580 + (low % 10 + 8) / 10;
}
fn pl_uint(builder, value) {
    let at = 64;
    if !value { at = at - 1; store8(pl_scratch + at, 48); }
    while value { let next = pl_udiv10(value); at = at - 1; store8(pl_scratch + at, 48 + value - next * 10); value = next; }
    return pl_append(builder, pl_scratch + at, 64 - at);
}
fn pl_int(builder, value) { if value < 0 { pl_char(builder, 45); value = -value; } return pl_uint(builder, value); }
fn pl_float(builder, word) { let text = pn_format(word); if pn_error { return -1; } return pl_append(builder, text, pn_size); }
fn pl_read_file(path, out, capacity) {
    let fd = syscall(2, path, 0x80000, 0, 0, 0, 0); if fd < 0 { return fd; }
    let size = 0; let error = 0; let active = 1;
    while active {
        let target = out + size; let room = capacity - size;
        if !room { target = pl_scratch + 256; room = 1; }
        let n = syscall(0, fd, target, room, 0, 0, 0);
        if n > 0 { if size == capacity { error = -90; active = 0; } else { size = size + n; } }
        else if n != -4 { active = 0; if n < 0 { error = n; } }
    }
    syscall(3, fd, 0, 0, 0, 0, 0); if error { return error; } store8(out + size, 0); return size;
}
fn pl_atomic_file(path, bytes, size) {
    let length = pl_size(path); if length > 4000 { return -36; }
    let builder = pl_scratch + 512; pl_builder(builder, pl_paths, 4096); pl_text(builder, path); pl_text(builder, ".tmp."); pl_uint(builder, syscall(39, 0, 0, 0, 0, 0, 0));
    let fd = syscall(2, pl_paths, 0x800c1, 384, 0, 0, 0); if fd < 0 { return fd; }
    let error = pl_write(fd, bytes, size);
    if !error { error = syscall(74, fd, 0, 0, 0, 0, 0); }
    syscall(3, fd, 0, 0, 0, 0, 0);
    if !error { error = syscall(82, pl_paths, path, 0, 0, 0, 0); }
    if error { syscall(87, pl_paths, 0, 0, 0, 0, 0); return error; }
    let slash = -1; let i = 0;
    while i < length { if load8(path + i) == 47 { slash = i; } i = i + 1; }
    let parent = pl_paths + 4096;
    if slash < 0 { pb_copy(parent, ".", 2); } else if !slash { pb_copy(parent, "/", 2); } else { pb_copy(parent, path, slash); store8(parent + slash, 0); }
    fd = syscall(2, parent, 0x90000, 0, 0, 0, 0);
    if fd < 0 { return fd; } error = syscall(74, fd, 0, 0, 0, 0, 0); syscall(3, fd, 0, 0, 0, 0, 0); return error;
}
fn pl_signals() {
    if pl_signal >= 0 { return pl_signal; }
    store64(pl_scratch + 256, (1 << 1) | (1 << 14));
    if syscall(14, 0, pl_scratch + 256, 0, 8, 0, 0) < 0 { return -1; }
    pl_signal = syscall(289, -1, pl_scratch + 256, 8, 0x80800, 0, 0); return pl_signal;
}
fn pl_ipv4(text, size, out) {
    let at = 0; let part = 0;
    while part < 4 {
        let before = at; let value = 0;
        while at < size && load8(text + at) >= 48 && load8(text + at) <= 57 { value = value * 10 + load8(text + at) - 48; if value > 255 { return 0; } at = at + 1; }
        if at == before { return 0; } store8(out + part, value); part = part + 1;
        if part < 4 { if at >= size || load8(text + at) != 46 { return 0; } at = at + 1; }
    }
    return at == size;
}
fn pl_sockaddr(out, host, size, port) {
    pb_zero(out, 16); pb_put16(out, 2); store8(out + 2, port >> 8); store8(out + 3, port);
    if size == 9 && pl_case_equal(host, size, "localhost") { store8(out + 4, 127); store8(out + 7, 1); return 1; }
    return pl_ipv4(host, size, out + 4);
}
fn pl_resolve_address(out, host, size, port) {
    if pl_sockaddr(out, host, size, port) { return 1; }
    if size < 1 || size > 255 { return 0; }
    if !pl_libc {
        pl_libc = ffi_open("libc.so.6"); if !pl_libc { return 0; }
        pl_resolve = ffi_symbol(pl_libc, "getaddrinfo"); pl_free_addresses = ffi_symbol(pl_libc, "freeaddrinfo");
    }
    if !pl_resolve || !pl_free_addresses { return 0; }
    let scratch = pl_paths + 4096; pb_zero(scratch, 128); pb_copy(scratch + 128, host, size); store8(scratch + 128 + size, 0);
    pb_put32(scratch + 4, 2); pb_put32(scratch + 8, 1);
    if ffi_call_i32(pl_resolve, scratch + 128, 0, scratch, scratch + 64, 0, 0) { return 0; }
    let addresses = load64(scratch + 64); let address = addresses; let found = 0;
    while address && !found {
        if pb_u32(address + 4) == 2 && pb_u32(address + 16) >= 16 { pb_copy(out, load64(address + 24), 16); found = 1; }
        address = load64(address + 40);
    }
    ffi_call(pl_free_addresses, addresses, 0, 0, 0, 0, 0); store8(out + 2, port >> 8); store8(out + 3, port); return found;
}
fn pl_listen(address, port_out) {
    let fd = syscall(41, 2, 0x80801, 0, 0, 0, 0); if fd < 0 { return fd; }
    store64(pl_scratch + 256, 1); syscall(54, fd, 1, 2, pl_scratch + 256, 4, 0);
    let error = syscall(49, fd, address, 16, 0, 0, 0);
    if !error { error = syscall(50, fd, 32, 0, 0, 0, 0); }
    if error { syscall(3, fd, 0, 0, 0, 0, 0); return error; }
    store64(pl_scratch + 256, 16); error = syscall(51, fd, address, pl_scratch + 256, 0, 0, 0);
    if error { syscall(3, fd, 0, 0, 0, 0, 0); return error; }
    store64(port_out, (load8(address + 2) << 8) | load8(address + 3)); return fd;
}
fn pl_wait(fd, events, deadline) {
    while 1 {
        let left = deadline - pl_now(); if left <= 0 { return 0; }
        store64(pl_scratch + 768, (fd & 0xffffffff) | (events << 32));
        let n = syscall(7, pl_scratch + 768, 1, left, 0, 0, 0);
        if n > 0 { return 1; } if n != -4 { return 0; }
    }
    return 0;
}
fn pl_connect(address, deadline) {
    let fd = syscall(41, 2, 0x80801, 0, 0, 0, 0); if fd < 0 { return fd; }
    let error = syscall(42, fd, address, 16, 0, 0, 0);
    if error == -115 && pl_wait(fd, 4, deadline) {
        store64(pl_scratch + 256, 0); store64(pl_scratch + 264, 4);
        error = syscall(55, fd, 1, 4, pl_scratch + 256, pl_scratch + 264, 0);
        if !error && pb_u32(pl_scratch + 256) { error = -1; }
    }
    if error { syscall(3, fd, 0, 0, 0, 0, 0); return -1; } return fd;
}
