// One thread block runs a whole GRU sequence. Each work item computes one
// recurrent gate of one batch row from the previous states in shared memory;
// the block then applies the gates. Operations repeat the unrolled graph's order,
// so states match the per-step graph and exported inference bit for bit.
import "../ml/kernels/ops.flex";
fn gpu_launch_word(index) {return 0;}
fn gpu_barrier() {return 0;}
fn gpu_shared_load_u32(offset) {return 0;}
fn gpu_shared_store_u32(offset,value) {return 0;}
fn kernel(index,input,output,count) {
    let saved=gpu_launch_word(0);let wh=gpu_launch_word(1);let bh=gpu_launch_word(2);let meta=gpu_launch_word(3);
    let batch=gpu_load_u64(meta+160);let width=gpu_load_u64(meta+168);let length=gpu_load_u64(meta+176);let threads=gpu_load_u64(meta+184);let gates=width*3;let states=batch*width;
    // Shared layout: previous states [batch][width], then recurrent gates [batch][gates].
    // Dot products issue eight loads before adding them in the original order.
    let e=index;while e<states {gpu_shared_store_u32(e*4,0);e=e+threads;}gpu_barrier();let t=0;
    while t<length {
        let p=index;while p<batch*gates {let b=vk_quotient(p,gates);let k=p-b*gates;let sum=0;let i=0;while i<width {let w0=gpu_load_u32(wh+((i+0)*gates+k)*4);let w1=gpu_load_u32(wh+((i+1)*gates+k)*4);let w2=gpu_load_u32(wh+((i+2)*gates+k)*4);let w3=gpu_load_u32(wh+((i+3)*gates+k)*4);let w4=gpu_load_u32(wh+((i+4)*gates+k)*4);let w5=gpu_load_u32(wh+((i+5)*gates+k)*4);let w6=gpu_load_u32(wh+((i+6)*gates+k)*4);let w7=gpu_load_u32(wh+((i+7)*gates+k)*4);sum=vk_add(sum,vk_mul(gpu_shared_load_u32((b*width+i+0)*4),w0));sum=vk_add(sum,vk_mul(gpu_shared_load_u32((b*width+i+1)*4),w1));sum=vk_add(sum,vk_mul(gpu_shared_load_u32((b*width+i+2)*4),w2));sum=vk_add(sum,vk_mul(gpu_shared_load_u32((b*width+i+3)*4),w3));sum=vk_add(sum,vk_mul(gpu_shared_load_u32((b*width+i+4)*4),w4));sum=vk_add(sum,vk_mul(gpu_shared_load_u32((b*width+i+5)*4),w5));sum=vk_add(sum,vk_mul(gpu_shared_load_u32((b*width+i+6)*4),w6));sum=vk_add(sum,vk_mul(gpu_shared_load_u32((b*width+i+7)*4),w7));i=i+8;}
            gpu_shared_store_u32((states+p)*4,vk_add(sum,gpu_load_u32(bh+k*4)));p=p+threads;}
        gpu_barrier();e=index;
        while e<states {let b=vk_quotient(e,width);let j=e-b*width;let x=input+(t*batch+b)*gates*4;let hx=(states+b*gates+j)*4;
            let r=vk_sigmoid(vk_add(gpu_load_u32(x+j*4),gpu_shared_load_u32(hx)));let z=vk_sigmoid(vk_add(gpu_load_u32(x+(width+j)*4),gpu_shared_load_u32(hx+width*4)));
            let hn=gpu_shared_load_u32(hx+width*8);let s=vk_sigmoid(vk_mul(0x40000000,vk_add(gpu_load_u32(x+(width*2+j)*4),vk_mul(r,hn))));let candidate=vk_sub(vk_mul(0x40000000,s),0x3f800000);
            // The backward scan reads these instead of recomputing the recurrent product.
            let keep=saved+((t*batch+b)*width*4+j)*4;gpu_store_u32(keep,r);gpu_store_u32(keep+width*4,z);gpu_store_u32(keep+width*8,s);gpu_store_u32(keep+width*12,hn);
            let h=vk_add(vk_mul(vk_sub(0x3f800000,z),candidate),vk_mul(z,gpu_shared_load_u32(e*4)));gpu_store_u32(output+((t*batch+b)*width+j)*4,h);gpu_shared_store_u32(e*4,h);e=e+threads;}
        gpu_barrier();t=t+1;
    }return 0;
}
fn main() {return 78;}
