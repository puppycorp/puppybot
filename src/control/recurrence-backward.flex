// Reverse GRU scan, kept apart from the general gradient kernel so its large
// thread block is not limited by that kernel's register use.
import "../ml/kernels/ops.flex";
fn gpu_launch_word(index) {return 0;}
fn gpu_barrier() {return 0;}
fn gpu_shared_load_u32(offset) {return 0;}
fn gpu_shared_store_u32(offset,value) {return 0;}
// Reverse GRU scan in one block, using the gates the forward scan saved per
// step (r, z, s, hn). Gate gradients are kept for the recurrent weight
// reductions. Shared layout: carried state gradients, gate gradients, and three
// partial sums of each carried gradient.
fn ptg_recurrence(index,gradient,output,ix,states,meta) {
    let batch=gpu_load_u64(meta);let width=gpu_load_u64(meta+8);let length=gpu_load_u64(meta+16);let gates=gpu_load_u64(meta+40);let transposed=gpu_load_u64(meta+48);let threads=gpu_load_u64(meta+56);let saved=gpu_load_u64(meta+64);
    let size=width*3;let n=batch*width;let r1=width*4;let r2=width*8;let r3=width*12;let r4=width*16;let r5=width*20;let r6=width*24;let r7=width*28;let r8=width*32;let e=index;while e<n {gpu_shared_store_u32(e*4,0);e=e+threads;}let t=length;gpu_barrier();
    while t {t=t-1;e=index;
        while e<n {let b=vk_quotient(e,width);let j=e-b*width;let keep=saved+((t*batch+b)*width*4+j)*4;
            let r=gpu_load_u32(keep);let z=gpu_load_u32(keep+width*4);let s=gpu_load_u32(keep+width*8);let hn=gpu_load_u32(keep+width*12);let candidate=vk_sub(vk_mul(0x40000000,s),0x3f800000);
            let h=0;if t {h=gpu_load_u32(states+((t-1)*n+e)*4);}let dh=vk_add(gpu_load_u32(gradient+(t*n+e)*4),gpu_shared_load_u32(e*4));
            // h=(1-z)c+zh', c=2*sigmoid(2a)-1 with a=inn+r*hn.
            let da=vk_mul(vk_mul(vk_mul(dh,vk_sub(0x3f800000,z)),0x40800000),vk_mul(s,vk_sub(0x3f800000,s)));
            let dr=vk_mul(vk_mul(da,hn),vk_mul(r,vk_sub(0x3f800000,r)));let dz=vk_mul(vk_mul(dh,vk_sub(h,candidate)),vk_mul(z,vk_sub(0x3f800000,z)));
            let o=output+(t*batch+b)*size*4;let g=gates+(t*batch+b)*size*4;let shared=(n+b*size+j)*4;let dn=vk_mul(da,r);
            gpu_store_u32(o+j*4,vk_add(gpu_load_u32(o+j*4),dr));gpu_store_u32(o+(width+j)*4,vk_add(gpu_load_u32(o+(width+j)*4),dz));gpu_store_u32(o+(width*2+j)*4,vk_add(gpu_load_u32(o+(width*2+j)*4),da));
            gpu_store_u32(g+j*4,dr);gpu_store_u32(g+(width+j)*4,dz);gpu_store_u32(g+(width*2+j)*4,dn);
            gpu_shared_store_u32(shared,dr);gpu_shared_store_u32(shared+width*4,dz);gpu_shared_store_u32(shared+width*8,dn);gpu_shared_store_u32(e*4,vk_mul(dh,z));e=e+threads;}
        // Each work item sums two adjacent carried gradients: one 64-bit load fetches both weights.
        gpu_barrier();let q=index*2;
        while q<n*3 {let part=vk_quotient(q,n);e=q-part*n;let b=vk_quotient(e,width);let j=e-b*width;let w=transposed+(part*width*width+j)*4;let h=(n+b*size+part*width)*4;let last=h+width*4;let s0=0;let s1=0;
            while h<last {let a0=gpu_load_u64(w);let a1=gpu_load_u64(w+r1);let a2=gpu_load_u64(w+r2);let a3=gpu_load_u64(w+r3);let a4=gpu_load_u64(w+r4);let a5=gpu_load_u64(w+r5);let a6=gpu_load_u64(w+r6);let a7=gpu_load_u64(w+r7);
                let v0=gpu_shared_load_u32(h);let v1=gpu_shared_load_u32(h+4);let v2=gpu_shared_load_u32(h+8);let v3=gpu_shared_load_u32(h+12);let v4=gpu_shared_load_u32(h+16);let v5=gpu_shared_load_u32(h+20);let v6=gpu_shared_load_u32(h+24);let v7=gpu_shared_load_u32(h+28);s0=vk_add(s0,vk_mul(a0&0xffffffff,v0));s1=vk_add(s1,vk_mul((a0>>32)&0xffffffff,v0));s0=vk_add(s0,vk_mul(a1&0xffffffff,v1));s1=vk_add(s1,vk_mul((a1>>32)&0xffffffff,v1));s0=vk_add(s0,vk_mul(a2&0xffffffff,v2));s1=vk_add(s1,vk_mul((a2>>32)&0xffffffff,v2));s0=vk_add(s0,vk_mul(a3&0xffffffff,v3));s1=vk_add(s1,vk_mul((a3>>32)&0xffffffff,v3));s0=vk_add(s0,vk_mul(a4&0xffffffff,v4));s1=vk_add(s1,vk_mul((a4>>32)&0xffffffff,v4));s0=vk_add(s0,vk_mul(a5&0xffffffff,v5));s1=vk_add(s1,vk_mul((a5>>32)&0xffffffff,v5));s0=vk_add(s0,vk_mul(a6&0xffffffff,v6));s1=vk_add(s1,vk_mul((a6>>32)&0xffffffff,v6));s0=vk_add(s0,vk_mul(a7&0xffffffff,v7));s1=vk_add(s1,vk_mul((a7>>32)&0xffffffff,v7));w=w+r8;h=h+32;}
            let out=(n*4+q)*4;gpu_shared_store_u32(out,s0);gpu_shared_store_u32(out+4,s1);q=q+threads*2;}
        gpu_barrier();e=index;
        while e<n {gpu_shared_store_u32(e*4,vk_add(vk_add(vk_add(gpu_shared_load_u32(e*4),gpu_shared_load_u32((n*4+e)*4)),gpu_shared_load_u32((n*5+e)*4)),gpu_shared_load_u32((n*6+e)*4)));e=e+threads;}
        gpu_barrier();
    }return 0;
}
fn kernel(index,input,output,count) {
    if index>=count {return 0;}
    ptg_recurrence(index,input,output,gpu_launch_word(1),gpu_launch_word(2),gpu_launch_word(3));return 0;
}
fn main() {return 78;}
