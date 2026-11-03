// Training matrix products for the direct RDNA target. Each work item computes
// two adjacent columns of one output row, sharing every left-operand load; each
// column sums in the generic Pup kernel's order, so outputs match it bit for bit.
import "../ml/kernels/ops.flex";
fn gpu_launch_word(index) {return 0;}
fn kernel(index,input,output,count) {
    if index>=count {return 0;}
    let b=gpu_launch_word(0);let meta=gpu_launch_word(3);
    let m=gpu_load_u64(meta+80);let n=gpu_load_u64(meta+88);let k=gpu_load_u64(meta+120);let pairs=(n+1)/2;
    let r=vk_quotient(index,pairs);let col=(index-r*pairs)*2;let batch=vk_quotient(r,m);
    let x=input+r*k*4;let last=x+k*4;let y=b+(batch*k*n+col)*4;let line=n*4;let s0=0;let s1=0;
    // Even widths keep column pairs 8-byte aligned: one 64-bit load fetches both weights.
    if !(n&1) {while x<last {let v=gpu_load_u32(x);let w=gpu_load_u64(y);s0=vk_add(s0,vk_mul(v,w&0xffffffff));s1=vk_add(s1,vk_mul(v,(w>>32)&0xffffffff));x=x+4;y=y+line;}}
    else if col+1<n {while x<last {let v=gpu_load_u32(x);s0=vk_add(s0,vk_mul(v,gpu_load_u32(y)));s1=vk_add(s1,vk_mul(v,gpu_load_u32(y+4)));x=x+4;y=y+line;}}
    else {while x<last {s0=vk_add(s0,vk_mul(gpu_load_u32(x),gpu_load_u32(y)));x=x+4;y=y+line;}}
    let out=output+(r*n+col)*4;gpu_store_u32(out,s0);if col+1<n {gpu_store_u32(out+4,s1);}return 0;
}
fn main() {return 78;}
