// Training convolutions for the direct RDNA target (one group, no padding). Each
// work item computes 8 consecutive output channels at one position of two
// consecutive frames, loading every weight once for both. Each channel sums in
// the generic Pup kernel's channel, row and column order, so outputs match it
// bit for bit.
import "../ml/kernels/ops.flex";
fn gpu_launch_word(index) {return 0;}
fn kernel(index,input,output,count) {
    if index>=count {return 0;}
    let weights=gpu_launch_word(1);let bias=gpu_launch_word(2);let meta=gpu_launch_word(3);
    let cin=gpu_load_u64(meta+104);let ih=gpu_load_u64(meta+112);let iw=gpu_load_u64(meta+120);let frames=gpu_load_u64(meta+64);let cout=gpu_load_u64(meta+72);let oh=gpu_load_u64(meta+80);let ow=gpu_load_u64(meta+88);
    let k=gpu_load_u64(meta+160);let stride=gpu_load_u64(meta+168);let groups=vk_quotient(cout,8);
    let ox=vk_remainder(index,ow);let oy=vk_remainder(vk_quotient(index,ow),oh);let group=vk_remainder(vk_quotient(index,ow*oh),groups);let batch=vk_quotient(index,ow*oh*groups)*2;
    // An odd last frame repeats the first frame's loads and stores only its own outputs.
    let second=batch+1<frames;let next=0;if second {next=cin*ih*iw*4;}
    let first=group*8;let filter=cin*k*k*4;let f1=filter;let f2=filter*2;let f3=filter*3;let f4=filter*4;let f5=filter*5;let f6=filter*6;let f7=filter*7;let line=iw*4;
    let s0=0;let s1=0;let s2=0;let s3=0;let s4=0;let s5=0;let s6=0;let s7=0;let t0=0;let t1=0;let t2=0;let t3=0;let t4=0;let t5=0;let t6=0;let t7=0;
    let source=input+((batch*cin*ih+oy*stride)*iw+ox*stride)*4;let w=weights+first*filter;let ci=0;
    while ci<cin {let row=source;let y=0;
        while y<k {let x=row;let last=row+k*4;
            while x<last {let v=gpu_load_u32(x);let u=gpu_load_u32(x+next);let c0=gpu_load_u32(w);s0=vk_add(s0,vk_mul(v,c0));t0=vk_add(t0,vk_mul(u,c0));let c1=gpu_load_u32(w+f1);s1=vk_add(s1,vk_mul(v,c1));t1=vk_add(t1,vk_mul(u,c1));let c2=gpu_load_u32(w+f2);s2=vk_add(s2,vk_mul(v,c2));t2=vk_add(t2,vk_mul(u,c2));let c3=gpu_load_u32(w+f3);s3=vk_add(s3,vk_mul(v,c3));t3=vk_add(t3,vk_mul(u,c3));let c4=gpu_load_u32(w+f4);s4=vk_add(s4,vk_mul(v,c4));t4=vk_add(t4,vk_mul(u,c4));let c5=gpu_load_u32(w+f5);s5=vk_add(s5,vk_mul(v,c5));t5=vk_add(t5,vk_mul(u,c5));let c6=gpu_load_u32(w+f6);s6=vk_add(s6,vk_mul(v,c6));t6=vk_add(t6,vk_mul(u,c6));let c7=gpu_load_u32(w+f7);s7=vk_add(s7,vk_mul(v,c7));t7=vk_add(t7,vk_mul(u,c7));x=x+4;w=w+4;}row=row+line;y=y+1;}
        source=source+ih*line;ci=ci+1;}
    let plane=oh*ow*4;let after=cout*plane;let out=output+(((batch*cout+first)*oh+oy)*ow+ox)*4;if bias {let b0=gpu_load_u32(bias+(first+0)*4);s0=vk_add(s0,b0);t0=vk_add(t0,b0);}gpu_store_u32(out+0*plane,s0);if second {gpu_store_u32(out+after+0*plane,t0);}if bias {let b1=gpu_load_u32(bias+(first+1)*4);s1=vk_add(s1,b1);t1=vk_add(t1,b1);}gpu_store_u32(out+1*plane,s1);if second {gpu_store_u32(out+after+1*plane,t1);}if bias {let b2=gpu_load_u32(bias+(first+2)*4);s2=vk_add(s2,b2);t2=vk_add(t2,b2);}gpu_store_u32(out+2*plane,s2);if second {gpu_store_u32(out+after+2*plane,t2);}if bias {let b3=gpu_load_u32(bias+(first+3)*4);s3=vk_add(s3,b3);t3=vk_add(t3,b3);}gpu_store_u32(out+3*plane,s3);if second {gpu_store_u32(out+after+3*plane,t3);}if bias {let b4=gpu_load_u32(bias+(first+4)*4);s4=vk_add(s4,b4);t4=vk_add(t4,b4);}gpu_store_u32(out+4*plane,s4);if second {gpu_store_u32(out+after+4*plane,t4);}if bias {let b5=gpu_load_u32(bias+(first+5)*4);s5=vk_add(s5,b5);t5=vk_add(t5,b5);}gpu_store_u32(out+5*plane,s5);if second {gpu_store_u32(out+after+5*plane,t5);}if bias {let b6=gpu_load_u32(bias+(first+6)*4);s6=vk_add(s6,b6);t6=vk_add(t6,b6);}gpu_store_u32(out+6*plane,s6);if second {gpu_store_u32(out+after+6*plane,t6);}if bias {let b7=gpu_load_u32(bias+(first+7)*4);s7=vk_add(s7,b7);t7=vk_add(t7,b7);}gpu_store_u32(out+7*plane,s7);if second {gpu_store_u32(out+after+7*plane,t7);}return 0;
}
fn main() {return 78;}
