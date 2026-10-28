// Starting, reversing and stopping are rare but decide whole-episode success.
global pt_stop_weight=0x4014000000000000;
fn pt_control_weight(mask,speed,previous) {
    let weight=mask;if f64_lt(f64_magnitude(speed),0x3f847ae147ae147b) {weight=f64_mul(weight,pt_stop_weight);}
    if f64_gt(f64_magnitude(f64_sub(speed,previous)),0x3fc999999999999a) {weight=f64_mul(weight,0x4020000000000000);}return weight;
}
