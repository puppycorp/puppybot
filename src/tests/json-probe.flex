import "../host/json.flex";
fn main() {
    if !pl_init() { return 1; }
    let input = alloc(16385); let out = alloc(65536); let builder = alloc(32); let header = alloc(16);
    while 1 {
        let at = 0;
        while at < 8 { let n = syscall(0, 0, header + at, 8 - at, 0, 0, 0); if !n && !at { return 0; } if n <= 0 { return 2; } at = at + n; }
        let size = load64(header); if size < 0 || size > 16384 { return 3; } at = 0;
        while at < size { let n = syscall(0, 0, input + at, size - at, 0, 0, 0); if n <= 0 { return 4; } at = at + n; }
        let node = pj_parse(input, size); pl_builder(builder, out, 65536); if node { pj_emit(builder, node); }
        store64(header, node != 0 && !load64(builder + 24)); store64(header + 8, load64(builder + 8));
        if pl_write(1, header, 16) || pl_write(1, out, load64(builder + 8)) { return 5; }
    }
    return 0;
}
