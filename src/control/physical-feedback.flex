// Translate the physical-agent's own commanded drive into the visual actor's
// seven feedback values. A real contact source is not available here: callers
// must explicitly opt in to zero contact and may only use this diagnostically.
import "observation.flex";
fn pc_feedback(drive, previous, out) {
    vc_require(pj_kind(drive) == 3 && pj_count(drive) == 3, "invalid drive feedback");
    vc_copy(out, previous, 8); let i = 0;
    while i < 3 {
        let value = pj_real_node(pj_index(drive, i));
        if i == 2 { value = f64_div(f64_sub(value, f64_from_i64(90)), f64_from_i64(45)); }
        else { value = f64_div(value, f64_from_i64(100)); }
        vc_require(!pj_error && f64_is_finite(value) && f64_le(f64_magnitude(value), PB_ONE), "invalid own-drive feedback");
        pb_put32(out + 8 + i * 4, pb_f64_to_f32(value)); i = i + 1;
    }
    pb_put32(out + 20, 0); pb_put32(out + 24, 0); return out;
}
