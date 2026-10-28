// Offline evaluation math for the training-only recurrent pose readout.
import "../../../flex/control/host.flex";

fn qp_relative_pose(initial,pose,target) {
    let dx=f64_sub(load64(pose),load64(initial));let dy=f64_sub(load64(pose+8),load64(initial+8));let heading=load64(initial+16);let c=f64_cos(heading);let s=f64_sin(heading);
    store64(target,f64_div(f64_add(f64_mul(c,dx),f64_mul(s,dy)),f64_from_i64(8)));store64(target+8,f64_div(f64_sub(f64_mul(c,dy),f64_mul(s,dx)),f64_from_i64(8)));
    let angle=pb_wrap_pi(f64_sub(load64(pose+16),heading));store64(target+16,f64_sin(angle));store64(target+24,f64_cos(angle));return 0;
}
fn qp_predict_pose(weights,bias,hidden,prediction) {
    let axis=0;while axis<4 {let value=pb_read_float(bias+axis*4);let i=0;while i<256 {value=f64_add(value,f64_mul(pb_read_float(weights+(i*4+axis)*4),pb_read_float(hidden+i*4)));i=i+1;}pb_put32(prediction+axis*4,pb_f64_to_f32(value));axis=axis+1;}return 0;
}
fn qp_errors(target,prediction,errors) {
    let f=pb_read_float(prediction);let s=pb_read_float(prediction+4);let dx=f64_mul(f64_sub(f,load64(target)),f64_from_i64(8));let dy=f64_mul(f64_sub(s,load64(target+8)),f64_from_i64(8));
    store64(errors,f64_hypot(dx,dy));store64(errors+8,f64_mul(f64_hypot(load64(target),load64(target+8)),f64_from_i64(8)));
    let sine=pb_read_float(prediction+8);let cosine=pb_read_float(prediction+12);let valid=f64_ge(f64_add(f64_mul(sine,sine),f64_mul(cosine,cosine)),vc_number(1,1000000));store64(errors+24,valid);store64(errors+16,0);
    if valid {let predicted=f64_atan2(sine,cosine);let actual=f64_atan2(load64(target+16),load64(target+24));store64(errors+16,f64_magnitude(pb_wrap_pi(f64_sub(predicted,actual))));}return 0;
}
