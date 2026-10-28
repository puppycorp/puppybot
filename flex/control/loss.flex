import "actions.flex";
global pt_softmax_scratch=0;
global pt_log_reciprocals=0;
// Keep the original normalization for single-phase batches and for the
// default loss. Balanced training gives each present phase half the weight.
fn pt_phase_scale(mask,label,total,positive,negative,balanced) {
    if balanced && f64_gt(positive,0) && f64_gt(negative,0) {let count=negative;if f64_gt(label,0) {count=positive;}return f64_div(mask,f64_mul(f64_from_i64(2),count));}
    return f64_div(mask,total);
}
// Return labels are privileged training supervision, never an actor input.
// Validation keeps the ordinary weights for comparable checkpoint selection.
fn pt_return_control_weight(weight,label,training,milli) {
    if training && milli && f64_gt(label,0) {return f64_mul(weight,vc_number(milli,1000));}return weight;
}
// Contact is the robot's own drive feedback; it is already an actor input.
// Keep validation and default training unchanged for comparable selection.
fn pt_contact_control_weight(weight,contact,training,milli) {
    if training && milli && f64_gt(contact,0) {return f64_mul(weight,vc_number(milli,1000));}return weight;
}
fn pt_phase_mask(supervision,valid,active,from_valid) {
    if !active {return 0;}if from_valid {return valid;}return supervision;
}
fn pt_phase_consistency_pair(previous,current,previous_mask,current_mask) {
    return pb_u32(previous_mask)==0x3f800000 && pb_u32(current_mask)==0x3f800000 && pb_u32(previous+8)==pb_u32(current+8);
}
fn pt_phase_probability(logit) {
    vc_require(f64_is_finite(logit),"nonfinite phase logit");let exp=f64_exp(pb_neg(f64_magnitude(logit)));let probability=f64_div(PB_ONE,f64_add(PB_ONE,exp));if f64_lt(logit,0) {probability=f64_mul(exp,probability);}return probability;
}
fn pt_phase_consistency_loss(previous,current,weight,previous_seed,current_seed) {
    let a=pt_phase_probability(previous);let b=pt_phase_probability(current);let delta=f64_sub(a,b);let two=f64_from_i64(2);
    let da=f64_mul(f64_mul(two,weight),f64_mul(delta,f64_mul(a,f64_sub(PB_ONE,a))));
    let db=pb_neg(f64_mul(f64_mul(two,weight),f64_mul(delta,f64_mul(b,f64_sub(PB_ONE,b)))));
    pb_put32(previous_seed,pb_f64_to_f32(f64_add(pb_read_float(previous_seed),da)));pb_put32(current_seed,pb_f64_to_f32(f64_add(pb_read_float(current_seed),db)));
    return f64_mul(weight,f64_mul(delta,delta));
}
fn pt_log1p(x) {
    // x is in [0,1]. atanh series has |y| <= 1/3. Host f64 division is slow, so the
    // series multiplies by reciprocals computed once; only reported loss values use it.
    if !pt_log_reciprocals {pt_log_reciprocals=alloc(128);let k=1;while k<=31 {store64(pt_log_reciprocals+(k-1)*4,f64_div(PB_ONE,f64_from_i64(k)));k=k+2;}}
    let y=f64_div(x,f64_add(0x4000000000000000,x));let square=f64_mul(y,y);let power=y;let sum=0;let i=1;
    while i<=31 {sum=f64_add(sum,f64_mul(power,load64(pt_log_reciprocals+(i-1)*4)));power=f64_mul(power,square);i=i+2;}return f64_mul(0x4000000000000000,sum);
}
fn pt_log_sum(x) {
    let exponent=0;while f64_gt(x,0x4000000000000000) {x=f64_mul(x,0x3fe0000000000000);exponent=exponent+1;}
    return f64_add(pt_log1p(f64_sub(x,PB_ONE)),f64_mul(f64_from_i64(exponent),0x3fe62e42fefa39ef));
}
fn pt_binary_loss(logit,label,weight,seed) {
    let exp=f64_exp(pb_neg(f64_magnitude(logit)));let probability=f64_div(PB_ONE,f64_add(PB_ONE,exp));if f64_lt(logit,0) {probability=f64_mul(exp,probability);}
    pb_put32(seed,pb_f64_to_f32(f64_mul(weight,f64_sub(probability,label))));
    return f64_mul(weight,f64_add(f64_sub(pb_fmax(logit,0),f64_mul(logit,label)),pt_log1p(exp)));
}
fn pt_event_mask(targets,index,batch) {
    let mask=pb_read_float(targets+index*16+12);if index>=batch {mask=f64_mul(mask,pb_read_float(targets+(index-batch)*16+12));}return mask;
}
fn pt_event_label(targets,index,batch) {
    // Targets describe the pre-action frame. The first return-labelled image
    // is the image that triggered RGB consumption, not the following frame.
    let phase=pb_read_float(targets+index*16+8);if index<batch {return phase;}if pb_u32(targets+(index-batch)*16+8) {return 0;}return phase;
}
fn pt_event_weight(targets,index,batch) {
    let weight=pt_event_mask(targets,index,batch);if pt_event_label(targets,index,batch) {weight=f64_mul(weight,0x4049000000000000);}return weight;
}
fn pt_categorical_loss(prediction,target,mask,weight,seed) {
    let kind=0;if f64_gt(mask,0) {kind=ca_class(pb_read_float(target),pb_read_float(target+4));vc_require(kind>=0,"categorical training requires exact seven-class oracle targets");}
    let maximum=pb_read_float(prediction);let i=0;while i<7 {let value=pb_read_float(prediction+i*4);vc_require(f64_is_finite(value),"nonfinite categorical logit");maximum=pb_fmax(maximum,value);i=i+1;}
    // Each exponential is computed once and reused for the probability.
    if !pt_softmax_scratch {pt_softmax_scratch=alloc(56);}let exps=pt_softmax_scratch;let sum=0;i=0;while i<7 {let e=f64_exp(f64_sub(pb_read_float(prediction+i*4),maximum));store64(exps+i*8,e);sum=f64_add(sum,e);i=i+1;}
    i=0;while i<7 {let probability=f64_div(load64(exps+i*8),sum);let label=0;if i==kind {label=PB_ONE;}pb_put32(seed+i*4,pb_f64_to_f32(f64_mul(weight,f64_sub(probability,label))));i=i+1;}
    return f64_mul(weight,f64_add(f64_sub(maximum,pb_read_float(prediction+kind*4)),pt_log_sum(sum)));
}
// Only discourage reversals where two supervised oracle commands agree on a
// nonzero direction within the same phase. Stops, phase changes, padding and
// teacher-requested reversals remain unconstrained.
fn pt_reversal_pair(previous,current) {
    if !pb_u32(previous+12) || !pb_u32(current+12) || pb_u32(previous+8)!=pb_u32(current+8) {return 0;}
    let a=pb_read_float(previous+4);let b=pb_read_float(current+4);
    return (f64_gt(a,0) && f64_gt(b,0)) || (f64_lt(a,0) && f64_lt(b,0));
}
fn pt_action_probabilities(prediction,out) {
    let maximum=pb_read_float(prediction);let i=0;while i<7 {let value=pb_read_float(prediction+i*4);vc_require(f64_is_finite(value),"nonfinite categorical logit");maximum=pb_fmax(maximum,value);i=i+1;}
    let sum=0;i=0;while i<7 {let value=f64_exp(f64_sub(pb_read_float(prediction+i*4),maximum));store64(out+i*8,value);sum=f64_add(sum,value);i=i+1;}
    i=0;while i<7 {store64(out+i*8,f64_div(load64(out+i*8),sum));i=i+1;}return 0;
}
fn pt_reversal_loss(previous,current,weight,previous_seed,current_seed,scratch) {
    pt_action_probabilities(previous,scratch);pt_action_probabilities(current,scratch+56);let af=0;let ar=0;let bf=0;let br=0;let i=0;
    while i<6 {if i<3 {af=f64_add(af,load64(scratch+i*8));bf=f64_add(bf,load64(scratch+56+i*8));}else {ar=f64_add(ar,load64(scratch+i*8));br=f64_add(br,load64(scratch+56+i*8));}i=i+1;}
    let expected=f64_add(f64_mul(af,br),f64_mul(ar,bf));i=0;
    while i<7 {let a=0;let b=0;if i<3 {a=br;b=ar;}else if i<6 {a=bf;b=af;}
        let da=f64_mul(weight,f64_mul(load64(scratch+i*8),f64_sub(a,expected)));let db=f64_mul(weight,f64_mul(load64(scratch+56+i*8),f64_sub(b,expected)));
        pb_put32(previous_seed+i*4,pb_f64_to_f32(f64_add(pb_read_float(previous_seed+i*4),da)));pb_put32(current_seed+i*4,pb_f64_to_f32(f64_add(pb_read_float(current_seed+i*4),db)));i=i+1;}
    return f64_mul(weight,expected);
}
fn pt_pose_loss(prediction,target,weight,seed) {
    let loss=0;let i=0;while i<4 {let value=pb_read_float(prediction+i*4);let expected=pb_read_float(target+i*4);vc_require(f64_is_finite(value) && f64_is_finite(expected),"nonfinite memory-pose value");let delta=f64_sub(value,expected);loss=f64_add(loss,f64_mul(weight,f64_mul(delta,delta)));pb_put32(seed+i*4,pb_f64_to_f32(f64_mul(f64_from_i64(2),f64_mul(weight,delta))));i=i+1;}return loss;
}
fn pt_target_loss(prediction,target,weight,seed) {
    let loss=0;let i=0;while i<2 {let value=pb_read_float(prediction+i*4);let expected=pb_read_float(target+i*4);vc_require(f64_is_finite(value) && f64_is_finite(expected),"nonfinite target-position value");let delta=f64_sub(value,expected);loss=f64_add(loss,f64_mul(weight,f64_mul(delta,delta)));pb_put32(seed+i*4,pb_f64_to_f32(f64_mul(f64_from_i64(2),f64_mul(weight,delta))));i=i+1;}return loss;
}
fn pt_heat_cell(coordinate,side) {
    vc_require(side==84 || side==128,"unsupported heatmap image size");let kernel=8;let stride=4;if side==128 {kernel=12;stride=6;}
    let pixel=f64_mul(f64_add(coordinate,PB_ONE),f64_from_i64(side/2));let centre=vc_number(kernel-1,2);
    return pb_max(0,pb_min(19,f64_to_i64_nearest(f64_div(f64_sub(pixel,centre),f64_from_i64(stride)))));
}
fn pt_heat_loss_sized(prediction,target,weight,seed,side) {
    // Supervise the nearest first-convolution cell and 16 separated negatives.
    if !f64_gt(weight,0) {return 0;}let col=pt_heat_cell(pb_read_float(target),side);let row=pt_heat_cell(pb_read_float(target+4),side);let positive=row*20+col;
    let loss=pt_binary_loss(pb_read_float(prediction+positive*4),PB_ONE,f64_mul(weight,vc_number(1,2)),seed+positive*4);let k=0;let selected=0;
    while selected<16 {let cell=(positive+1+k*23)%400;k=k+1;let dx=pb_abs(cell%20-col);let dy=pb_abs(cell/20-row);if dx>1 || dy>1 {loss=f64_add(loss,pt_binary_loss(pb_read_float(prediction+cell*4),0,f64_mul(weight,vc_number(1,32)),seed+cell*4));selected=selected+1;}}
    return loss;
}
fn pt_heat_loss(prediction,target,weight,seed) {return pt_heat_loss_sized(prediction,target,weight,seed,84);}
fn pt_heat_absence_loss(prediction,index,weight,seed) {
    // After the simulator consumes the brick, supervise distributed negative
    // cells. This label is used by training only, never by the actor.
    if !f64_gt(weight,0) {return 0;}let loss=0;let k=0;while k<16 {let cell=(index*97+k*23)%400;loss=f64_add(loss,pt_binary_loss(pb_read_float(prediction+cell*4),0,f64_mul(weight,vc_number(1,16)),seed+cell*4));k=k+1;}return loss;
}
