import "../host/linux.flex";

fn main() {
    if !pl_init() { return 1; }
    let record = alloc(1040); let builder = alloc(32); let out = alloc(256);
    while 1 {
        let at = 0;
        while at < 16 {
            let n = syscall(0, 0, record + at, 16 - at, 0, 0, 0);
            if !n && !at { return 0; } if n <= 0 { return 2; } at = at + n;
        }
        let op = load64(record); let value = load64(record + 8);
        if !op {
            if value < 0 || value > 1024 { return 3; } at = 0;
            while at < value { let n = syscall(0, 0, record + 16 + at, value - at, 0, 0, 0); if n <= 0 { return 4; } at = at + n; }
            let word = pn_parse(record + 16, value); store64(out, pn_error); store64(out + 8, word); if pl_write(1, out, 16) { return 5; }
        } else {
            let text = pn_format(value); store64(out, pn_size); if !text || pn_error { return 6; }
            if pl_write(1, out, 8) || pl_write(1, text, pn_size) { return 7; }
        }
    }
    return 0;
}
