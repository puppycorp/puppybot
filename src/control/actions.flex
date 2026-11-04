// Joint action classes match the training oracle's six drive primitives and stop.
// Decoding chooses one complete command; logits are never averaged into controls.
import "host.flex";
fn ca_steering_bits(index) {if index==6 || index%3==1 {return 0;}if index%3==0 {return 0xbf19999a;}return 0x3f19999a;}
fn ca_speed_bits(index) {if index==6 {return 0;}if index<3 {return 0x3f800000;}return 0xbf800000;}
fn ca_class(steering,speed) {
    let i=0;while i<7 {if f64_lt(f64_magnitude(f64_sub(steering,pb_f32_to_f64(ca_steering_bits(i)))),vc_number(1,100000)) && f64_lt(f64_magnitude(f64_sub(speed,pb_f32_to_f64(ca_speed_bits(i)))),vc_number(1,100000)) {return i;}i=i+1;}return -1;
}
fn ca_decode(logits,output) {
    let best=0;let maximum=pb_read_float(logits);let i=0;while i<7 {let value=pb_read_float(logits+i*4);if !f64_is_finite(value) {return -1;}if f64_gt(value,maximum) {maximum=value;best=i;}i=i+1;}
    pb_put32(output,ca_steering_bits(best));pb_put32(output+4,ca_speed_bits(best));return best;
}
