// Portable WebSocket wire helpers shared by Linux peers and future firmware.
import "../core/words.flex";

fn pw_rotate(word, count) { return ((word << count) | (word >> (32 - count))) & 0xffffffff; }
fn pw_sha1(out, text, size, scratch) {
    let h0 = 0x67452301; let h1 = 0xefcdab89; let h2 = 0x98badcfe; let h3 = 0x10325476; let h4 = 0xc3d2e1f0;
    let blocks = (size + 9 + 63) / 64; let block = 0;
    while block < blocks {
        let i = 0;
        while i < 16 {
            let value = 0; let j = 0;
            while j < 4 {
                let at = block * 64 + i * 4 + j; let byte = 0;
                if at < size { byte = load8(text + at); } else if at == size { byte = 128; }
                else if at >= blocks * 64 - 8 { byte = (size * 8 >> ((blocks * 64 - 1 - at) * 8)) & 255; }
                value = (value << 8) | byte; j = j + 1;
            }
            store64(scratch + i * 8, value); i = i + 1;
        }
        while i < 80 { store64(scratch + i * 8, pw_rotate(load64(scratch + (i - 3) * 8) ^ load64(scratch + (i - 8) * 8) ^ load64(scratch + (i - 14) * 8) ^ load64(scratch + (i - 16) * 8), 1)); i = i + 1; }
        let a = h0; let b = h1; let c = h2; let d = h3; let e = h4; i = 0;
        while i < 80 {
            let f = 0; let k = 0;
            if i < 20 { f = (b & c) | ((~b) & d); k = 0x5a827999; }
            else if i < 40 { f = b ^ c ^ d; k = 0x6ed9eba1; }
            else if i < 60 { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
            else { f = b ^ c ^ d; k = 0xca62c1d6; }
            let temp = (pw_rotate(a, 5) + f + e + k + load64(scratch + i * 8)) & 0xffffffff;
            e = d; d = c; c = pw_rotate(b, 30); b = a; a = temp; i = i + 1;
        }
        h0 = (h0 + a) & 0xffffffff; h1 = (h1 + b) & 0xffffffff; h2 = (h2 + c) & 0xffffffff; h3 = (h3 + d) & 0xffffffff; h4 = (h4 + e) & 0xffffffff;
        block = block + 1;
    }
    store64(scratch, h0); store64(scratch + 8, h1); store64(scratch + 16, h2); store64(scratch + 24, h3); store64(scratch + 32, h4);
    let i = 0; while i < 20 { store8(out + i, load64(scratch + (i / 4) * 8) >> ((3 - i % 4) * 8)); i = i + 1; } return 20;
}
fn pw_base64(out, text, size) {
    let alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"; let at = 0; let i = 0;
    while i < size {
        let value = load8(text + i) << 16;
        if i + 1 < size { value = value | (load8(text + i + 1) << 8); } if i + 2 < size { value = value | load8(text + i + 2); }
        store8(out + at, load8(alphabet + ((value >> 18) & 63))); store8(out + at + 1, load8(alphabet + ((value >> 12) & 63)));
        let c = 61; if i + 1 < size { c = load8(alphabet + ((value >> 6) & 63)); } store8(out + at + 2, c);
        c = 61; if i + 2 < size { c = load8(alphabet + (value & 63)); } store8(out + at + 3, c);
        i = i + 3; at = at + 4;
    }
    store8(out + at, 0); return at;
}
fn pw_base64_digit(c) {
    if c >= 65 && c <= 90 { return c - 65; } if c >= 97 && c <= 122 { return c - 71; }
    if c >= 48 && c <= 57 { return c + 4; } if c == 43 { return 62; } if c == 47 { return 63; } return -1;
}
fn pw_key(text, size) {
    if size != 24 || load8(text + 22) != 61 || load8(text + 23) != 61 { return 0; }
    let i = 0; while i < 22 { if pw_base64_digit(load8(text + i)) < 0 { return 0; } i = i + 1; }
    return (pw_base64_digit(load8(text + 21)) & 15) == 0;
}
fn pw_accept(out, key, size, scratch) {
    if !pw_key(key, size) { return 0; }
    pb_copy(scratch, key, size); pb_copy(scratch + size, "258EAFA5-E914-47DA-95CA-C5AB0DC85B11", 36);
    pw_sha1(scratch + 128, scratch, size + 36, scratch + 256); return pw_base64(out, scratch + 128, 20);
}
fn pw_frame(out, capacity, opcode, data, size, masked, key) {
    if size < 0 || size > 2048 { return -90; }
    let header = 2; if size >= 126 { header = 4; } let mask_size = 0; if masked { mask_size = 4; }
    if header + mask_size + size > capacity { return -90; }
    store8(out, 128 | opcode); let bit = 0; if masked { bit = 128; }
    if size < 126 { store8(out + 1, bit | size); } else { store8(out + 1, bit | 126); store8(out + 2, size >> 8); store8(out + 3, size); }
    if masked { pb_put32(out + header, key); }
    let i = 0; while i < size { let value = load8(data + i); if masked { value = value ^ ((key >> ((i % 4) * 8)) & 255); } store8(out + header + mask_size + i, value); i = i + 1; }
    return header + mask_size + size;
}
// Parser returns frame bytes, 0 for incomplete, or negative RFC close code.
// Metadata: opcode, FIN, payload offset, payload length, masking key.
fn pw_parse(data, size, require_mask, meta) {
    if size < 2 { return 0; }
    let first = load8(data); let second = load8(data + 1); let opcode = first & 15;
    if first & 112 || (opcode != 0 && opcode != 1 && opcode != 2 && opcode != 8 && opcode != 9 && opcode != 10) { return -1002; }
    if ((second >> 7) != require_mask) { return -1002; }
    let n = second & 127; let header = 2;
    if n == 126 { if size < 4 { return 0; } n = (load8(data + 2) << 8) | load8(data + 3); header = 4; if n < 126 { return -1002; } }
    else if n == 127 {
        if size < 10 { return 0; } let i = 2; while i < 8 { if load8(data + i) { return -1009; } i = i + 1; }
        n = (load8(data + 8) << 8) | load8(data + 9); if n < 65536 { return -1002; } return -1009;
    }
    if n > 2048 { return -1009; }
    if opcode >= 8 && (!(first & 128) || n > 125) { return -1002; }
    let key = 0;
    if require_mask { if size < header + 4 { return 0; } key = pb_u32(data + header); header = header + 4; }
    if size < header + n { return 0; }
    store64(meta, opcode); store64(meta + 8, (first >> 7) & 1); store64(meta + 16, header); store64(meta + 24, n); store64(meta + 32, key);
    return header + n;
}
