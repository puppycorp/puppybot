// Deterministic FP32 reverse-mode kernels. Each thread owns one destination
// gradient; reductions gather their contributions, avoiding floating atomics.
import "../ml/kernels/ops.flex";
fn gpu_launch_word(index) {return 0;}
fn gpu_f32_sqrt(value) {return vk_pack_f32(f64_sqrt(vk_unpack_f32(value)));}
fn ptg_product(shape,start,end) {let n=1;while start<end {n=n*gpu_load_u64(shape+start*8);start=start+1;}return n;}
fn ptg_binary(index,a,b,g,meta,role) {
    let shape=meta+96;if role {shape=meta+128;}
    let base=0;let stride=1;let repeats=1;let axis=4;let q=index;
    while axis {axis=axis-1;let d=gpu_load_u64(shape+axis*8);let o=gpu_load_u64(meta+64+axis*8);
        base=base+vk_remainder(q,d)*stride;q=vk_quotient(q,d);stride=stride*o;if d==1 {repeats=repeats*o;}}
    let sum=0;let r=0;
    while r<repeats {
        let out=base;let rest=r;stride=1;axis=4;
        while axis {axis=axis-1;let d=gpu_load_u64(shape+axis*8);let o=gpu_load_u64(meta+64+axis*8);
            if d==1 {out=out+vk_remainder(rest,o)*stride;rest=vk_quotient(rest,o);}stride=stride*o;}
        let x=gpu_load_u32(a+vk_broadcast(out,meta+64,meta+96)*4);
        let y=gpu_load_u32(b+vk_broadcast(out,meta+64,meta+128)*4);
        let scale=0x3f800000;let op=gpu_load_u64(meta);
        if op==4 && role {scale=0xbf800000;}
        else if op==5 {scale=y;if role {scale=x;}}
        else if op==6 {scale=vk_div(0x3f800000,y);if role {scale=vk_sub(0,vk_div(x,vk_mul(y,y)));}}
        else if op==7 {scale=0;if !role && vk_max(x,y)==x {scale=0x3f800000;}if role && vk_max(x,y)!=x {scale=0x3f800000;}}
        sum=vk_add(sum,vk_mul(gpu_load_u32(g+out*4),scale));r=r+1;
    }return sum;
}
fn ptg_join(index,g,meta,role) {
    let axis=gpu_load_u64(meta+160);let inner=ptg_product(meta+64,axis+1,4);
    let size=gpu_load_u64(meta+96+axis*8);if role {size=gpu_load_u64(meta+128+axis*8);}
    let coordinate=vk_remainder(vk_quotient(index,inner),size);let outer=vk_quotient(index,inner*size);
    let op=gpu_load_u64(meta);let out_size=gpu_load_u64(meta+64+axis*8);
    if op==26 {coordinate=coordinate-gpu_load_u64(meta+168);if coordinate<0 || coordinate>=out_size {return 0;}}
    else if role {coordinate=coordinate+gpu_load_u64(meta+96+axis*8);}
    return gpu_load_u32(g+((outer*out_size+coordinate)*inner+vk_remainder(index,inner))*4);
}
fn ptg_matmul(index,a,b,g,meta,role) {
    // The control graph uses ordinary rank-two matrices throughout.
    let m=gpu_load_u64(meta+80);let n=gpu_load_u64(meta+88);let k=gpu_load_u64(meta+120);let sum=0;let i=0;
    if !role {let row=vk_quotient(index,k);let col=vk_remainder(index,k);
        while i<n {sum=vk_add(sum,vk_mul(gpu_load_u32(g+(row*n+i)*4),gpu_load_u32(b+(col*n+i)*4)));i=i+1;}}
    else {let row=vk_quotient(index,n);let col=vk_remainder(index,n);
        while i<m {sum=vk_add(sum,vk_mul(gpu_load_u32(a+(i*k+row)*4),gpu_load_u32(g+(i*n+col)*4)));i=i+1;}}
    return sum;
}
fn ptg_convolution(index,a,w,g,meta,role) {
    let batch=gpu_load_u64(meta+64);let cout=gpu_load_u64(meta+72);let oh=gpu_load_u64(meta+80);let ow=gpu_load_u64(meta+88);
    let cin=gpu_load_u64(meta+104);let ih=gpu_load_u64(meta+112);let iw=gpu_load_u64(meta+120);
    let k=gpu_load_u64(meta+160);let stride=gpu_load_u64(meta+168);let pad=gpu_load_u64(meta+176);let sum=0;
    if role==3 {let b=0;while b<batch {let p=0;while p<oh*ow {sum=vk_add(sum,gpu_load_u32(g+((b*cout+index)*oh*ow+p)*4));p=p+1;}b=b+1;}return sum;}
    if role==2 {
        let kx=vk_remainder(index,k);let ky=vk_remainder(vk_quotient(index,k),k);
        let ci=vk_remainder(vk_quotient(index,k*k),cin);let co=vk_quotient(index,cin*k*k);let b=0;
        while b<batch {let y=0;while y<oh {let iy=y*stride+ky-pad;let x=0;
            while x<ow {let ix=x*stride+kx-pad;if iy>=0 && iy<ih && ix>=0 && ix<iw {
                sum=vk_add(sum,vk_mul(gpu_load_u32(a+((b*cin+ci)*ih*iw+iy*iw+ix)*4),gpu_load_u32(g+((b*cout+co)*oh*ow+y*ow+x)*4)));}x=x+1;}y=y+1;}b=b+1;}
    } else {
        let ix=vk_remainder(index,iw);let iy=vk_remainder(vk_quotient(index,iw),ih);
        let ci=vk_remainder(vk_quotient(index,ih*iw),cin);let b=vk_quotient(index,cin*ih*iw);let co=0;
        while co<cout {let ky=0;while ky<k {let yy=iy+pad-ky;let kx=0;
            while kx<k {let xx=ix+pad-kx;if yy>=0 && xx>=0 && vk_remainder(yy,stride)==0 && vk_remainder(xx,stride)==0 {
                let y=vk_quotient(yy,stride);let x=vk_quotient(xx,stride);if y<oh && x<ow {
                    sum=vk_add(sum,vk_mul(gpu_load_u32(w+((co*cin+ci)*k*k+ky*k+kx)*4),gpu_load_u32(g+((b*cout+co)*oh*ow+y*ow+x)*4)));}}
                kx=kx+1;}ky=ky+1;}co=co+1;}
    }return sum;
}
fn kernel(index,input,output,count) {
    if index>=count {return 0;}
    let mode=gpu_launch_word(0);let a=gpu_launch_word(1);let b=gpu_launch_word(2);let meta=gpu_launch_word(3);
    if mode==100 {gpu_store_u32(output+index*4,0);return 0;}
    if mode==103 {gpu_store_u32(output+index*4,vk_div(gpu_f32_from_i64(load8(input+index)),0x437f0000));return 0;}
    if mode==101 {
        let sum=0;let i=index*256;let end=i+256;let total=gpu_load_u64(meta);
        while i<end && i<total {let g=gpu_load_u32(input+i*4);sum=vk_add(sum,vk_mul(g,g));i=i+1;}
        gpu_store_u32(output+index*4,sum);return 0;
    }
    if mode==102 {
        let gradient=vk_mul(gpu_load_u32(input+index*4),gpu_load_u32(meta));
        let m=vk_add(vk_mul(gpu_load_u32(a+index*4),0x3f666666),vk_mul(gradient,0x3dcccccd));
        let v=vk_add(vk_mul(gpu_load_u32(b+index*4),0x3f7fbe77),vk_mul(vk_mul(gradient,gradient),0x3a83126f));
        gpu_store_u32(a+index*4,m);gpu_store_u32(b+index*4,v);
        let corrected_m=vk_mul(m,gpu_load_u32(meta+4));let corrected_v=vk_mul(v,gpu_load_u32(meta+8));
        let update=vk_div(vk_mul(corrected_m,gpu_load_u32(meta+12)),vk_add(gpu_f32_sqrt(corrected_v),0x322bcc77));
        gpu_store_u32(output+index*4,vk_sub(gpu_load_u32(output+index*4),update));return 0;
    }
    let role=mode;let op=gpu_load_u64(meta);let value=0;
    if op>=3 && op<=7 {value=ptg_binary(index,a,b,input,meta,role);}
    else if op==24 {let y=gpu_load_u32(a+index*4);value=vk_mul(gpu_load_u32(input+index*4),vk_mul(y,vk_sub(0x3f800000,y)));}
    else if op==25 || op==26 {value=ptg_join(index,input,meta,role);}
    else if op==29 {value=ptg_matmul(index,a,b,input,meta,role);}
    else if op==12 {value=ptg_convolution(index,a,b,input,meta,role);}
    gpu_store_u32(output+index*4,vk_add(gpu_load_u32(output+index*4),value));return 0;
}
fn main() {return 78;}
