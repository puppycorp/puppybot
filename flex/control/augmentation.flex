// Training-only reflection keeps a complete recurrent history in one frame.
import "host.flex";
global pm_rng=7;
global pf_rng=7;
// Draw a separate per-sequence mask so feedback augmentation cannot change
// the training permutation or the existing image-mirror random stream.
fn pf_mask(batch,count,milli) {
    vc_require(batch>=1 && count>=0 && count<=batch && milli>=0 && milli<=1000,"invalid feedback mask dimensions");let mask=0;let b=0;
    while b<count {pf_rng=(pf_rng*1103515245+12345)&2147483647;if pf_rng%1000<milli {mask=mask|(1<<b);}b=b+1;}return mask;
}
fn pf_neutral_drive(proprio) {let i=0;while i<5 {pb_put32(proprio+i*4,0);i=i+1;}return 0;}
fn pm_mask(batch,count) {
    let mask=0;let b=0;while b<batch && b<count {pm_rng=(pm_rng*1103515245+12345)&2147483647;if (pm_rng>>15)&1 {mask=mask|(1<<b);}b=b+1;}return mask;
}
fn pm_feedback(proprio,target,valid) {
    if !valid {return 0;}
    pb_put32(proprio,pb_u32(proprio)^0x80000000);let left=pb_u32(proprio+8);pb_put32(proprio+8,pb_u32(proprio+12));pb_put32(proprio+12,left);
    pb_put32(proprio+16,pb_u32(proprio+16)^0x80000000);pb_put32(target,pb_u32(target)^0x80000000);return 0;
}
fn pm_pose(target,valid) {
    if !valid {return 0;}pb_put32(target+4,pb_u32(target+4)^0x80000000);pb_put32(target+8,pb_u32(target+8)^0x80000000);return 0;
}
fn pm_target(target,valid) {
    if valid {pb_put32(target,pb_u32(target)^0x80000000);}return 0;
}
