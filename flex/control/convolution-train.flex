// Training convolutions (one group, no padding). Each work item computes 8
// consecutive output channels at one position, loading every input once for
// all of them. Each channel sums in the generic Pup kernel's channel, row and
// column order, so outputs match it bit for bit.
import "../ml/kernels/ops.flex";
fn gpu_launch_word(index) {return 0;}
fn kernel(index,input,output,count) {
    if index>=count {return 0;}
    let weights=gpu_launch_word(1);let bias=gpu_launch_word(2);let meta=gpu_launch_word(3);
    let cin=gpu_load_u64(meta+104);let ih=gpu_load_u64(meta+112);let iw=gpu_load_u64(meta+120);let cout=gpu_load_u64(meta+72);let oh=gpu_load_u64(meta+80);let ow=gpu_load_u64(meta+88);
    let k=gpu_load_u64(meta+160);let stride=gpu_load_u64(meta+168);let groups=vk_quotient(cout,8);
    let ox=vk_remainder(index,ow);let oy=vk_remainder(vk_quotient(index,ow),oh);let group=vk_remainder(vk_quotient(index,ow*oh),groups);let batch=vk_quotient(index,ow*oh*groups);
    let first=group*8;let filter=cin*k*k*4;let s0=0;let s1=0;let s2=0;let s3=0;let s4=0;let s5=0;let s6=0;let s7=0;let ci=0;
    while ci<cin {let source=input+(((batch*cin+ci)*ih+oy*stride)*iw+ox*stride)*4;let y=0;
        while y<k {let row=source+y*iw*4;let w=weights+((first*cin+ci)*k+y)*k*4;let x=0;
            while x<k {let v=gpu_load_u32(row+x*4);s0=vk_add(s0,vk_mul(v,gpu_load_u32(w+0*filter+x*4)));s1=vk_add(s1,vk_mul(v,gpu_load_u32(w+1*filter+x*4)));s2=vk_add(s2,vk_mul(v,gpu_load_u32(w+2*filter+x*4)));s3=vk_add(s3,vk_mul(v,gpu_load_u32(w+3*filter+x*4)));s4=vk_add(s4,vk_mul(v,gpu_load_u32(w+4*filter+x*4)));s5=vk_add(s5,vk_mul(v,gpu_load_u32(w+5*filter+x*4)));s6=vk_add(s6,vk_mul(v,gpu_load_u32(w+6*filter+x*4)));s7=vk_add(s7,vk_mul(v,gpu_load_u32(w+7*filter+x*4)));x=x+1;}y=y+1;}
        ci=ci+1;}
    let plane=oh*ow*4;let out=output+(((batch*cout+first)*oh+oy)*ow+ox)*4;if bias {s0=vk_add(s0,gpu_load_u32(bias+(first+0)*4));}gpu_store_u32(out+0*plane,s0);if bias {s1=vk_add(s1,gpu_load_u32(bias+(first+1)*4));}gpu_store_u32(out+1*plane,s1);if bias {s2=vk_add(s2,gpu_load_u32(bias+(first+2)*4));}gpu_store_u32(out+2*plane,s2);if bias {s3=vk_add(s3,gpu_load_u32(bias+(first+3)*4));}gpu_store_u32(out+3*plane,s3);if bias {s4=vk_add(s4,gpu_load_u32(bias+(first+4)*4));}gpu_store_u32(out+4*plane,s4);if bias {s5=vk_add(s5,gpu_load_u32(bias+(first+5)*4));}gpu_store_u32(out+5*plane,s5);if bias {s6=vk_add(s6,gpu_load_u32(bias+(first+6)*4));}gpu_store_u32(out+6*plane,s6);if bias {s7=vk_add(s7,gpu_load_u32(bias+(first+7)*4));}gpu_store_u32(out+7*plane,s7);return 0;
}
fn main() {return 78;}
