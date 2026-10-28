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
    let size=width*3;let n=batch*width;let e=index;while e<n {gpu_shared_store_u32(e*4,0);e=e+threads;}let t=length;gpu_barrier();
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
        gpu_barrier();let q=index;
        while q<n*3 {let part=vk_quotient(q,n);e=q-part*n;let b=vk_quotient(e,width);let j=e-b*width;let sum=0;let k=part*width;
            while k<part*width+width {let w0=gpu_load_u32(transposed+((k+0)*width+j)*4);let w1=gpu_load_u32(transposed+((k+1)*width+j)*4);let w2=gpu_load_u32(transposed+((k+2)*width+j)*4);let w3=gpu_load_u32(transposed+((k+3)*width+j)*4);let w4=gpu_load_u32(transposed+((k+4)*width+j)*4);let w5=gpu_load_u32(transposed+((k+5)*width+j)*4);let w6=gpu_load_u32(transposed+((k+6)*width+j)*4);let w7=gpu_load_u32(transposed+((k+7)*width+j)*4);sum=vk_add(sum,vk_mul(w0,gpu_shared_load_u32((n+b*size+k+0)*4)));sum=vk_add(sum,vk_mul(w1,gpu_shared_load_u32((n+b*size+k+1)*4)));sum=vk_add(sum,vk_mul(w2,gpu_shared_load_u32((n+b*size+k+2)*4)));sum=vk_add(sum,vk_mul(w3,gpu_shared_load_u32((n+b*size+k+3)*4)));sum=vk_add(sum,vk_mul(w4,gpu_shared_load_u32((n+b*size+k+4)*4)));sum=vk_add(sum,vk_mul(w5,gpu_shared_load_u32((n+b*size+k+5)*4)));sum=vk_add(sum,vk_mul(w6,gpu_shared_load_u32((n+b*size+k+6)*4)));sum=vk_add(sum,vk_mul(w7,gpu_shared_load_u32((n+b*size+k+7)*4)));k=k+8;}
            gpu_shared_store_u32((n*4+q)*4,sum);q=q+threads;}
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
