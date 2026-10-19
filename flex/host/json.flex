// Bounded JSON tree for configuration and one request at a time. Strings are
// length-bearing UTF-8; numbers retain integer types and exact binary64 values.
import "linux.flex";

global pj_arena = 0;
global pj_used = 0;
global pj_source = 0;
global pj_size = 0;
global pj_at = 0;
global pj_depth = 0;
global pj_error = 0;
global pj_message = 0;
global pj_field = 0;

fn pj_fail(message) { pj_error = 1; pj_message = message; return 0; }
fn pj_take(size) {
    size = (size + 7) & -8;
    if size < 0 || size > 131072 - pj_used { return pj_fail("JSON storage limit exceeded"); }
    let out = pj_arena + pj_used; pj_used = pj_used + size; pb_zero(out, size); return out;
}
fn pj_node(kind, value, size) {
    let out = pj_take(48); if !out { return 0; }
    store64(out, kind); store64(out + 8, value); store64(out + 16, size); return out;
}
fn pj_kind(node) { if !node { return -1; } return load64(node); }
fn pj_value(node) { if !node { return 0; } return load64(node + 8); }
fn pj_count(node) { if !node { return 0; } return load64(node + 16); }
fn pj_ws() {
    while pj_at < pj_size {
        let c = load8(pj_source + pj_at); if c != 32 && c != 9 && c != 10 && c != 13 { return 0; } pj_at = pj_at + 1;
    }
    return 0;
}
fn pj_utf8_size(text, remaining) {
    if remaining < 1 { return 0; } let first = load8(text); let n = 0;
    if first < 128 { return 1; }
    if first >= 194 && first <= 223 { n = 2; }
    else if first >= 224 && first <= 239 { n = 3; }
    else if first >= 240 && first <= 244 { n = 4; } else { return 0; }
    if remaining < n { return 0; }
    let i = 1; while i < n { let c = load8(text + i); if c < 128 || c > 191 { return 0; } i = i + 1; }
    let second = load8(text + 1);
    if (first == 224 && second < 160) || (first == 237 && second >= 160) || (first == 240 && second < 144) || (first == 244 && second >= 144) { return 0; }
    return n;
}
fn pj_hex4() {
    if pj_size - pj_at < 4 { pj_fail("short Unicode escape"); return 0; }
    let value = 0; let i = 0;
    while i < 4 {
        let c = load8(pj_source + pj_at); pj_at = pj_at + 1; let digit = -1;
        if c >= 48 && c <= 57 { digit = c - 48; } else if c >= 65 && c <= 70 { digit = c - 55; } else if c >= 97 && c <= 102 { digit = c - 87; }
        if digit < 0 { pj_fail("invalid Unicode escape"); return 0; } value = value * 16 + digit; i = i + 1;
    }
    return value;
}
fn pj_utf8(out, value) {
    if value < 128 { store8(out, value); return 1; }
    if value < 2048 { store8(out, 192 | (value >> 6)); store8(out + 1, 128 | (value & 63)); return 2; }
    if value < 65536 { store8(out, 224 | (value >> 12)); store8(out + 1, 128 | ((value >> 6) & 63)); store8(out + 2, 128 | (value & 63)); return 3; }
    store8(out, 240 | (value >> 18)); store8(out + 1, 128 | ((value >> 12) & 63)); store8(out + 2, 128 | ((value >> 6) & 63)); store8(out + 3, 128 | (value & 63)); return 4;
}
fn pj_string() {
    if pj_at >= pj_size || load8(pj_source + pj_at) != 34 { return pj_fail("JSON string expected"); }
    pj_at = pj_at + 1; let end = pj_at;
    while end < pj_size && load8(pj_source + end) != 34 { if load8(pj_source + end) == 92 { end = end + 1; } end = end + 1; }
    if end >= pj_size { return pj_fail("unterminated JSON string"); }
    let out = pj_take(end - pj_at + 1); if !out { return 0; } let size = 0;
    while pj_at < end && !pj_error {
        let c = load8(pj_source + pj_at); pj_at = pj_at + 1;
        if c == 92 {
            c = load8(pj_source + pj_at); pj_at = pj_at + 1;
            if c == 34 || c == 92 || c == 47 { store8(out + size, c); size = size + 1; }
            else if c == 98 { store8(out + size, 8); size = size + 1; }
            else if c == 102 { store8(out + size, 12); size = size + 1; }
            else if c == 110 { store8(out + size, 10); size = size + 1; }
            else if c == 114 { store8(out + size, 13); size = size + 1; }
            else if c == 116 { store8(out + size, 9); size = size + 1; }
            else if c == 117 {
                let code = pj_hex4();
                if code >= 55296 && code <= 56319 {
                    if pj_size - pj_at < 6 || load8(pj_source + pj_at) != 92 || load8(pj_source + pj_at + 1) != 117 { return pj_fail("missing low Unicode surrogate"); }
                    pj_at = pj_at + 2; let low = pj_hex4();
                    if low < 56320 || low > 57343 { return pj_fail("invalid low Unicode surrogate"); }
                    code = 65536 + (code - 55296) * 1024 + low - 56320;
                } else if code >= 56320 && code <= 57343 { return pj_fail("unpaired Unicode surrogate"); }
                if pj_error { return 0; } size = size + pj_utf8(out + size, code);
            } else { return pj_fail("invalid JSON escape"); }
        } else {
            if c < 32 { return pj_fail("control byte in JSON string"); }
            let n = pj_utf8_size(pj_source + pj_at - 1, end - pj_at + 1);
            if !n { return pj_fail("invalid UTF-8 in JSON string"); }
            pb_copy(out + size, pj_source + pj_at - 1, n); size = size + n; pj_at = pj_at + n - 1;
        }
    }
    if pj_at != end { return pj_fail("invalid JSON string length"); } pj_at = pj_at + 1;
    return pj_node(2, out, size);
}
fn pj_number() {
    let before = pj_at; let floating = 0;
    while pj_at < pj_size {
        let c = load8(pj_source + pj_at);
        if c == 46 || c == 101 || c == 69 { floating = 1; }
        if (c >= 48 && c <= 57) || c == 45 || c == 43 || c == 46 || c == 101 || c == 69 { pj_at = pj_at + 1; } else { c = 0; }
        if !c { let size = pj_at - before; if !size { return pj_fail("JSON value expected"); } return pj_number_finish(before, size, floating); }
    }
    return pj_number_finish(before, pj_at - before, floating);
}
fn pj_number_finish(before, size, floating) {
    let word = pn_parse(pj_source + before, size); if pn_error { return pj_fail("invalid or out-of-range JSON number"); }
    if !floating {
        let integer = pl_integer(pj_source + before, size);
        if !pl_bad_number { return pj_node(1, integer, word); }
        if load8(pj_source + before) != 45 {
            integer = pl_unsigned_parse(pj_source + before, size); if !pl_bad_number { return pj_node(7, integer, word); }
        }
    }
    return pj_node(6, word, 0);
}
fn pj_literal(text, size, kind, value) {
    if pj_size - pj_at < size { return pj_fail("short JSON literal"); }
    let i = 0; while i < size { if load8(pj_source + pj_at + i) != load8(text + i) { return pj_fail("invalid JSON literal"); } i = i + 1; }
    pj_at = pj_at + size; return pj_node(kind, value, 0);
}
fn pj_parse_value() {
    pj_ws(); if pj_at >= pj_size { return pj_fail("JSON value expected"); }
    let c = load8(pj_source + pj_at);
    if c == 34 { return pj_string(); }
    if c == 110 { return pj_literal("null", 4, 0, 0); }
    if c == 116 { return pj_literal("true", 4, 5, 1); }
    if c == 102 { return pj_literal("false", 5, 5, 0); }
    if c == 123 || c == 91 {
        if pj_depth >= 32 { return pj_fail("JSON nesting exceeds 32 levels"); }
        pj_depth = pj_depth + 1; pj_at = pj_at + 1; let kind = 3; let close = 93;
        if c == 123 { kind = 4; close = 125; }
        let node = pj_node(kind, 0, 0); if !node { return 0; }
        pj_ws(); if pj_at < pj_size && load8(pj_source + pj_at) == close { pj_at = pj_at + 1; pj_depth = pj_depth - 1; return node; }
        let tail = 0; let active = 1;
        while active && !pj_error {
            let key = 0;
            if kind == 4 {
                key = pj_string(); if !key { return 0; } pj_ws();
                if pj_at >= pj_size || load8(pj_source + pj_at) != 58 { return pj_fail("JSON colon expected"); } pj_at = pj_at + 1;
            }
            let child = pj_parse_value(); if !child { return 0; }
            if key { store64(child + 32, pj_value(key)); store64(child + 40, pj_count(key)); }
            if tail { store64(tail + 24, child); } else { store64(node + 8, child); } tail = child;
            store64(node + 16, load64(node + 16) + 1); pj_ws();
            if pj_at >= pj_size { return pj_fail("unterminated JSON container"); }
            c = load8(pj_source + pj_at); pj_at = pj_at + 1;
            if c == close { active = 0; }
            else if c == 44 { pj_ws(); } else { return pj_fail("JSON comma expected"); }
        }
        pj_depth = pj_depth - 1; return node;
    }
    return pj_number();
}
fn pj_parse(source, size) {
    if !pj_arena { pj_arena = alloc(131072); }
    pj_used = 0; pj_source = source; pj_size = size; pj_at = 0; pj_depth = 0; pj_error = 0; pj_field = ""; pj_message = "invalid JSON";
    if pj_arena <= 0 { return pj_fail("cannot allocate JSON workspace"); }
    let node = pj_parse_value(); pj_ws();
    if pj_at != pj_size { pj_fail("trailing JSON input"); }
    if pj_error { return 0; } return node;
}
fn pj_get(object, name) {
    if pj_kind(object) != 4 { return 0; }
    let n = pl_size(name); let node = pj_value(object); let found = 0;
    while node {
        if load64(node + 40) == n {
            let key = load64(node + 32); let i = 0;
            while i < n && load8(key + i) == load8(name + i) { i = i + 1; }
            if i == n { found = node; }
        }
        node = load64(node + 24);
    }
    return found;
}
fn pj_index(array, index) {
    if pj_kind(array) != 3 || index < 0 { return 0; }
    let node = pj_value(array); while node && index { node = load64(node + 24); index = index - 1; } return node;
}
fn pj_need(object, name, kind) {
    pj_field = name; let node = pj_get(object, name);
    if pj_kind(node) != kind { return pj_fail("missing field or wrong JSON type"); } return node;
}
fn pj_integer(object, name, lo, hi) {
    let node = pj_need(object, name, 1); if !node { return 0; } let value = pj_value(node);
    if value < lo || value > hi { pj_fail("integer field is out of range"); return 0; } return value;
}
fn pj_real_node(node) {
    if pj_kind(node) == 6 { return pj_value(node); }
    if pj_kind(node) == 1 || pj_kind(node) == 7 { return pj_count(node); }
    pj_fail("number field expected"); return 0;
}
fn pj_real(object, name) { pj_field = name; return pj_real_node(pj_get(object, name)); }
fn pj_boolean(object, name) { return pj_value(pj_need(object, name, 5)); }
fn pj_string_field(object, name) { return pj_value(pj_need(object, name, 2)); }
fn pj_quote(builder, text, size) {
    pl_char(builder, 34); let i = 0; let hex = "0123456789abcdef";
    while i < size {
        let c = load8(text + i);
        if c == 34 || c == 92 { pl_char(builder, 92); pl_char(builder, c); }
        else if c < 32 { pl_text(builder, "\\u00"); pl_char(builder, load8(hex + (c >> 4))); pl_char(builder, load8(hex + (c & 15))); }
        else { pl_char(builder, c); } i = i + 1;
    }
    return pl_char(builder, 34);
}
fn pj_text(builder, text) { return pj_quote(builder, text, pl_size(text)); }
fn pj_bool_text(builder, value) { if value { return pl_text(builder, "true"); } return pl_text(builder, "false"); }

fn pj_emit(builder, node) {
    let kind = pj_kind(node);
    if kind == 0 { return pl_text(builder, "null"); }
    if kind == 1 { return pl_int(builder, pj_value(node)); }
    if kind == 7 { return pl_uint(builder, pj_value(node)); }
    if kind == 6 { return pl_float(builder, pj_value(node)); }
    if kind == 2 { return pj_quote(builder, pj_value(node), pj_count(node)); }
    if kind == 5 { return pj_bool_text(builder, pj_value(node)); }
    let open = 91; let close = 93; if kind == 4 { open = 123; close = 125; }
    pl_char(builder, open); let child = pj_value(node); let first = 1;
    while child {
        if !first { pl_char(builder, 44); } first = 0;
        if kind == 4 { pj_quote(builder, load64(child + 32), load64(child + 40)); pl_char(builder, 58); }
        pj_emit(builder, child); child = load64(child + 24);
    }
    return pl_char(builder, close);
}
