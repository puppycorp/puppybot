// Compare label cells against the centres of the actual convolution windows.
import "../control/loss.flex";
fn hr_reference(coordinate,side) {
    let kernel=8;let stride=4;if side==128 {kernel=12;stride=6;}
    let pixel=f64_mul(f64_add(coordinate,PB_ONE),vc_number(side,2));let best=0;let distance=0x7ff0000000000000;let i=0;
    while i<20 {let centre=vc_number(2*i*stride+kernel-1,2);let current=f64_magnitude(f64_sub(pixel,centre));if f64_lt(current,distance) {best=i;distance=current;}i=i+1;}return best;
}
fn main(argc,argv) {
    vc_init(argc,argv);let side=84;while side<=128 {let i= -99;while i<=99 {let value=vc_number(i*100+13,10000);vc_require(pt_heat_cell(value,side)==hr_reference(value,side),"heatmap label does not use the nearest convolution window");i=i+1;}side=side+44;}
    let prediction=alloc(1600);let target=alloc(8);let old=alloc(1600);let legacy=alloc(1600);let large=alloc(1600);pb_put32(target,pb_f64_to_f32(vc_number(-49,100)));pb_put32(target+4,pb_f64_to_f32(vc_number(-3,10)));
    let a=pt_heat_loss(prediction,target,PB_ONE,old);let b=pt_heat_loss_sized(prediction,target,PB_ONE,legacy,84);let c=pt_heat_loss_sized(prediction,target,PB_ONE,large,128);vc_require(f64_eq(a,b) && f64_eq(a,c),"uniform heatmap loss differs by resolution");let i=0;while i<400 {vc_require(pb_u32(old+i*4)==pb_u32(legacy+i*4),"84x84 heatmap seeds changed");i=i+1;}
    vc_require(pb_u32(old+(6*20+4)*4)==0xbe800000 && pb_u32(large+(7*20+5)*4)==0xbe800000,"heatmap supervision did not follow the actual receptive fields");pl_print(1,"Native heatmap resolution contracts passed.\n");return 0;
}
