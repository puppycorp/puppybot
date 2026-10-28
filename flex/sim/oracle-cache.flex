// Exact geometry-keyed memo for training-only labels. Overflow disables reuse.
global ps_oracle_key = 0;
global ps_oracle_saved_key = 0;
global ps_oracle_saved_reply = 0;
global ps_oracle_key_bytes = 0;
global ps_oracle_saved_bytes = 0;
global ps_oracle_cache_valid = 0;
global ps_oracle_cache_hits = 0;
global ps_oracle_cache_checks = 0;
global ps_oracle_cache_verify = 0;

fn ps_oracle_cache_reset() {
    ps_oracle_cache_valid = 0; ps_oracle_cache_hits = 0; ps_oracle_cache_checks = 0; return 0;
}
fn ps_oracle_key_begin() {
    if !ps_oracle_key { ps_oracle_key = alloc(65536); ps_oracle_saved_key = alloc(65536); ps_oracle_saved_reply = alloc(64); }
    ps_oracle_key_bytes = 0; return 0;
}
fn ps_oracle_key_add(data, bytes) {
    if ps_oracle_key_bytes < 0 { return 0; }
    if bytes < 0 || bytes > 65536 - ps_oracle_key_bytes { ps_oracle_key_bytes = -1; return 0; }
    pb_copy(ps_oracle_key + ps_oracle_key_bytes, data, bytes); ps_oracle_key_bytes = ps_oracle_key_bytes + bytes; return 1;
}
fn ps_oracle_key_word(value) {
    if ps_oracle_key_bytes < 0 || ps_oracle_key_bytes > 65528 { ps_oracle_key_bytes = -1; return 0; }
    store64(ps_oracle_key + ps_oracle_key_bytes, value); ps_oracle_key_bytes = ps_oracle_key_bytes + 8; return 1;
}
fn ps_oracle_cache_read(reply) {
    if !ps_oracle_cache_valid || ps_oracle_key_bytes <= 0 || ps_oracle_key_bytes != ps_oracle_saved_bytes { return 0; }
    let i = 0; while i < ps_oracle_key_bytes { if load8(ps_oracle_key + i) != load8(ps_oracle_saved_key + i) { return 0; } i = i + 1; }
    pb_copy(reply, ps_oracle_saved_reply, 64); ps_oracle_cache_hits = ps_oracle_cache_hits + 1; return 1;
}
fn ps_oracle_cache_save(reply) {
    ps_oracle_cache_valid = 0; if ps_oracle_key_bytes <= 0 || !load64(reply + 16) { return 0; }
    pb_copy(ps_oracle_saved_key, ps_oracle_key, ps_oracle_key_bytes); pb_copy(ps_oracle_saved_reply, reply, 64);
    ps_oracle_saved_bytes = ps_oracle_key_bytes; ps_oracle_cache_valid = 1; return 1;
}
