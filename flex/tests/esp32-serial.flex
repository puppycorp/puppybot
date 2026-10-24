// Native wire/bounds oracle. Input: [time_ms:u64, byte:u64] records on stdin.
import "../firmware/serial.flex";
fn main() {
    let input = alloc(1048576); let at = 0; let n = 1;
    while n > 0 && at < 1048576 { n = syscall(0, 0, input + at, 1048576 - at, 0, 0, 0); if n > 0 { at = at + n; } }
    if at % 16 { return 1; }
    let guard = alloc(448); let i = 0; while i < 448 { store8(guard + i, 165); i = i + 1; }
    let parser = guard + 64; i = 0; while i < 320 { store8(parser + i, 0); i = i + 1; }
    let wire = alloc(264); let row = alloc(16); let offset = 0;
    while offset < at {
        let result = pf_serial_byte(parser, load64(input + offset + 8), load64(input + offset));
        if result {
            store64(row, result); let size = 0;
            if result == 1 { size = pf_envelope(wire, load64(parser + 24), parser + 64, load64(parser + 32)); }
            store64(row + 8, size); syscall(1, 1, row, 16, 0, 0, 0); if size { syscall(1, 1, wire, size, 0, 0, 0); }
        }
        i = 0; while i < 64 { if load8(guard + i) != 165 || load8(guard + 384 + i) != 165 { return 2; } i = i + 1; }
        offset = offset + 16;
    } return 0;
}
