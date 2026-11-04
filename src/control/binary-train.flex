// Training elementwise arithmetic. Same results as the generic Pup kernel; operands
// that match the output, are scalars, or repeat one row skip the general broadcast.
import "../ml/kernels/ops.flex";
fn gpu_launch_word(index) {return 0;}
fn vb_offset(index,meta,shape) {
    let out=meta+64;let width=gpu_load_u64(out+24);
    if gpu_load_u64(shape)==1 && gpu_load_u64(shape+8)==1 && gpu_load_u64(shape+16)==1 {let last=gpu_load_u64(shape+24);if last==1 {return 0;}if last==width {return vk_remainder(index,width);}}
    if gpu_load_u64(shape)==gpu_load_u64(out) && gpu_load_u64(shape+8)==gpu_load_u64(out+8) && gpu_load_u64(shape+16)==gpu_load_u64(out+16) && gpu_load_u64(shape+24)==width {return index;}
    return vk_broadcast(index,out,shape);
}
fn kernel(index,input,output,count) {
    if index>=count {return 0;}
    let b=gpu_launch_word(0);let meta=gpu_launch_word(3);let op=gpu_load_u64(meta);
    let x=gpu_load_u32(input+vb_offset(index,meta,meta+96)*4);let y=gpu_load_u32(b+vb_offset(index,meta,meta+128)*4);let value=0;
    if op==3 {value=vk_add(x,y);}else if op==4 {value=vk_sub(x,y);}else if op==5 {value=vk_mul(x,y);}else if op==6 {value=vk_div(x,y);}else {value=vk_max(x,y);}
    gpu_store_u32(output+index*4,value);return 0;
}
fn main() {return 78;}
