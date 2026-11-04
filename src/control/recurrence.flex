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
    let batch=gpu_load_u64(meta+160);let width=gpu_load_u64(meta+168);let length=gpu_load_u64(meta+176);let threads=gpu_load_u64(meta+184);let gates=width*3;let states=batch*width;let row=gates*4;let r1=row;let r2=row*2;let r3=row*3;let r4=row*4;let r5=row*5;let r6=row*6;let r7=row*7;let r8=row*8;
    // Shared layout: previous states [batch][width], then recurrent gates [batch][gates].
    // Dot products issue eight loads before adding them in the original order.
    let e=index;while e<states {gpu_shared_store_u32(e*4,0);e=e+threads;}gpu_barrier();let t=0;
    while t<length {
        // Each work item computes two adjacent gates of one batch row: one 64-bit load fetches both weights.
        let p=index;while p<states*3/2 {let b=vk_quotient(p,gates/2);let k=(p-b*gates/2)*2;let w=wh+k*4;let h=b*width*4;let last=h+width*4;let s0=0;let s1=0;
            while h<last {let a0=gpu_load_u64(w);let a1=gpu_load_u64(w+r1);let a2=gpu_load_u64(w+r2);let a3=gpu_load_u64(w+r3);let a4=gpu_load_u64(w+r4);let a5=gpu_load_u64(w+r5);let a6=gpu_load_u64(w+r6);let a7=gpu_load_u64(w+r7);
                let v0=gpu_shared_load_u32(h);let v1=gpu_shared_load_u32(h+4);let v2=gpu_shared_load_u32(h+8);let v3=gpu_shared_load_u32(h+12);let v4=gpu_shared_load_u32(h+16);let v5=gpu_shared_load_u32(h+20);let v6=gpu_shared_load_u32(h+24);let v7=gpu_shared_load_u32(h+28);s0=vk_add(s0,vk_mul(v0,a0&0xffffffff));s1=vk_add(s1,vk_mul(v0,(a0>>32)&0xffffffff));s0=vk_add(s0,vk_mul(v1,a1&0xffffffff));s1=vk_add(s1,vk_mul(v1,(a1>>32)&0xffffffff));s0=vk_add(s0,vk_mul(v2,a2&0xffffffff));s1=vk_add(s1,vk_mul(v2,(a2>>32)&0xffffffff));s0=vk_add(s0,vk_mul(v3,a3&0xffffffff));s1=vk_add(s1,vk_mul(v3,(a3>>32)&0xffffffff));s0=vk_add(s0,vk_mul(v4,a4&0xffffffff));s1=vk_add(s1,vk_mul(v4,(a4>>32)&0xffffffff));s0=vk_add(s0,vk_mul(v5,a5&0xffffffff));s1=vk_add(s1,vk_mul(v5,(a5>>32)&0xffffffff));s0=vk_add(s0,vk_mul(v6,a6&0xffffffff));s1=vk_add(s1,vk_mul(v6,(a6>>32)&0xffffffff));s0=vk_add(s0,vk_mul(v7,a7&0xffffffff));s1=vk_add(s1,vk_mul(v7,(a7>>32)&0xffffffff));w=w+r8;h=h+32;}
            let out=(states+p*2)*4;gpu_shared_store_u32(out,vk_add(s0,gpu_load_u32(bh+k*4)));gpu_shared_store_u32(out+4,vk_add(s1,gpu_load_u32(bh+k*4+4)));p=p+threads;}
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
