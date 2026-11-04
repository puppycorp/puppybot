import "../control/loss.flex";
fn cw_close(a,b) {return f64_lt(f64_magnitude(f64_sub(a,b)),vc_number(1,100000));}
fn main(argc,argv) {
    vc_init(argc,argv);let base=f64_from_i64(3);
    vc_require(cw_close(pt_contact_control_weight(base,PB_ONE,1,2000),f64_from_i64(6)),"contact control weight was not applied");
    vc_require(cw_close(pt_contact_control_weight(base,0,1,2000),base) && cw_close(pt_contact_control_weight(base,PB_ONE,0,2000),base) && cw_close(pt_contact_control_weight(base,PB_ONE,1,0),base),"non-contact, validation or default weight changed");
    vc_require(cw_close(pt_contact_control_weight(0,PB_ONE,1,2000),0),"masked action received weight");
    let normal=pt_contact_control_weight(PB_ONE,0,1,2000);let contact=pt_contact_control_weight(PB_ONE,PB_ONE,1,2000);let total=f64_add(normal,contact);
    vc_require(cw_close(f64_div(normal,total),vc_number(1,3)) && cw_close(f64_div(contact,total),vc_number(2,3)),"contact batch normalization changed the relative weights");
    let combined=pt_contact_control_weight(pt_return_control_weight(PB_ONE,PB_ONE,1,2000),PB_ONE,1,2000);
    vc_require(cw_close(combined,f64_from_i64(4)),"contact and return weights did not compose");
    let logits=alloc(28);let target=alloc(8);let seed=alloc(28);let scratch=alloc(28);let i=0;while i<7 {pb_put32(logits+i*4,pb_f64_to_f32(vc_number(i-3,10)));i=i+1;}pb_put32(target,ca_steering_bits(1));pb_put32(target+4,ca_speed_bits(1));
    let weight=vc_number(2,3);let value=pt_categorical_loss(logits,target,PB_ONE,weight,seed);vc_require(f64_gt(value,0),"weighted categorical loss is empty");let epsilon=vc_number(1,1000);i=0;while i<7 {let original=pb_u32(logits+i*4);let x=pb_read_float(logits+i*4);pb_put32(logits+i*4,pb_f64_to_f32(f64_add(x,epsilon)));let plus=pt_categorical_loss(logits,target,PB_ONE,weight,scratch);pb_put32(logits+i*4,pb_f64_to_f32(f64_sub(x,epsilon)));let minus=pt_categorical_loss(logits,target,PB_ONE,weight,scratch);pb_put32(logits+i*4,original);let numeric=f64_div(f64_sub(plus,minus),f64_mul(f64_from_i64(2),epsilon));vc_require(f64_lt(f64_magnitude(f64_sub(numeric,pb_read_float(seed+i*4))),vc_number(1,1000)),"contact-weighted action gradient differs from finite difference");i=i+1;}
    pl_print(1,"Contact control weighting, masks, validation and gradients passed.\n");return 0;
}
