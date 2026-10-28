// Joint-action sampling uses only network logits and a reproducible local RNG.
import "../../../flex/control/actions.flex";
global ps_inverse_temperature=0x3ff0000000000000;
global ps_seed=73;
global ps_rng=73;
fn ps_quantile(logits,output,quantile,inverse_temperature) {
    if !f64_is_finite(quantile) || f64_lt(quantile,0) || !f64_lt(quantile,PB_ONE) || !f64_is_finite(inverse_temperature) || !f64_gt(inverse_temperature,0) {return -1;}
    let maximum=pb_read_float(logits);let i=0;while i<7 {let value=pb_read_float(logits+i*4);if !f64_is_finite(value) {return -1;}maximum=pb_fmax(maximum,value);i=i+1;}
    let masses=alloc(56);let total=0;i=0;while i<7 {let mass=f64_exp(f64_mul(f64_sub(pb_read_float(logits+i*4),maximum),inverse_temperature));store64(masses+i*8,mass);total=f64_add(total,mass);i=i+1;}
    let threshold=f64_mul(quantile,total);let cumulative=0;let selected=6;i=0;while i<7 {cumulative=f64_add(cumulative,load64(masses+i*8));if f64_lt(threshold,cumulative) {selected=i;i=7;}else {i=i+1;}}
    pb_put32(output,ca_steering_bits(selected));pb_put32(output+4,ca_speed_bits(selected));syscall(11,masses,56,0,0,0,0);return selected;
}
fn ps_decode(logits,output) {
    if !ps_inverse_temperature {return ca_decode(logits,output);}
    ps_rng=(ps_rng*1103515245+12345)&2147483647;let quantile=f64_div(f64_add(f64_from_i64(ps_rng),vc_number(1,2)),f64_from_i64(2147483648));return ps_quantile(logits,output,quantile,ps_inverse_temperature);
}
fn ps_reset(hidden) {
    let i=0;while i<128 {if pb_u32(hidden+i*4)&2147483647 {return 0;}i=i+1;}ps_rng=ps_seed;return 1;
}
