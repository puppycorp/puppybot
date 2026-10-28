// Deterministic FP32 reverse-mode kernels. Each thread owns one destination
// gradient; reductions gather their contributions, avoiding floating atomics.
import "../ml/kernels/ops.flex";
fn gpu_launch_word(index) {return 0;}
fn gpu_f32_sqrt(value) {return vk_pack_f32(f64_sqrt(vk_unpack_f32(value)));}
fn ptg_product(shape,start,end) {let n=1;while start<end {n=n*gpu_load_u64(shape+start*8);start=start+1;}return n;}
fn ptg_offset(index,meta,shape) {
    let out=meta+64;let width=gpu_load_u64(out+24);
    if gpu_load_u64(shape)==1 && gpu_load_u64(shape+8)==1 && gpu_load_u64(shape+16)==1 {let last=gpu_load_u64(shape+24);if last==1 {return 0;}if last==width {return vk_remainder(index,width);}}
    if gpu_load_u64(shape)==gpu_load_u64(out) && gpu_load_u64(shape+8)==gpu_load_u64(out+8) && gpu_load_u64(shape+16)==gpu_load_u64(out+16) && gpu_load_u64(shape+24)==width {return index;}
    return vk_broadcast(index,out,shape);
}
fn ptg_binary(index,a,b,g,meta,role) {
    let shape=meta+96;if role {shape=meta+128;}
    // A bias added across rows sums one column, in the same row order as the general path.
    let width=gpu_load_u64(meta+88);
    if gpu_load_u64(meta)==3 && gpu_load_u64(shape)==1 && gpu_load_u64(shape+8)==1 && gpu_load_u64(shape+16)==1 && gpu_load_u64(shape+24)==width {
        let rows=gpu_load_u64(meta+64)*gpu_load_u64(meta+72)*gpu_load_u64(meta+80);let total=0;let row=0;while row<rows {total=vk_add(total,gpu_load_u32(g+(row*width+index)*4));row=row+1;}return total;
    }
    let base=0;let stride=1;let repeats=1;let axis=4;let q=index;
    while axis {axis=axis-1;let d=gpu_load_u64(shape+axis*8);let o=gpu_load_u64(meta+64+axis*8);
        base=base+vk_remainder(q,d)*stride;q=vk_quotient(q,d);stride=stride*o;if d==1 {repeats=repeats*o;}}
    let sum=0;let r=0;
    // An operand with the output's shape has no reduction; locate the other operand directly.
    if repeats==1 && gpu_load_u64(shape)==gpu_load_u64(meta+64) && gpu_load_u64(shape+8)==gpu_load_u64(meta+72) && gpu_load_u64(shape+16)==gpu_load_u64(meta+80) && gpu_load_u64(shape+24)==width {
        let x=gpu_load_u32(a+ptg_offset(index,meta,meta+96)*4);let y=gpu_load_u32(b+ptg_offset(index,meta,meta+128)*4);let scale=0x3f800000;let op=gpu_load_u64(meta);
        if op==4 && role {scale=0xbf800000;}else if op==5 {scale=y;if role {scale=x;}}
        else if op==6 {scale=vk_div(0x3f800000,y);if role {scale=vk_sub(0,vk_div(x,vk_mul(y,y)));}}
        else if op==7 {scale=0;if !role && vk_max(x,y)==x {scale=0x3f800000;}if role && vk_max(x,y)!=x {scale=0x3f800000;}}
        return vk_add(0,vk_mul(gpu_load_u32(g+index*4),scale));
    }
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
    if !role {let row=vk_quotient(index,k);let col=vk_remainder(index,k);let x=g+row*n*4;let y=b+col*n*4;
        // Both rows are contiguous: four loads before the adds, in the original order.
        while i+4<=n {let x0=gpu_load_u32(x+i*4);let x1=gpu_load_u32(x+i*4+4);let x2=gpu_load_u32(x+i*4+8);let x3=gpu_load_u32(x+i*4+12);
            let y0=gpu_load_u32(y+i*4);let y1=gpu_load_u32(y+i*4+4);let y2=gpu_load_u32(y+i*4+8);let y3=gpu_load_u32(y+i*4+12);
            sum=vk_add(sum,vk_mul(x0,y0));sum=vk_add(sum,vk_mul(x1,y1));sum=vk_add(sum,vk_mul(x2,y2));sum=vk_add(sum,vk_mul(x3,y3));i=i+4;}
        while i<n {sum=vk_add(sum,vk_mul(gpu_load_u32(x+i*4),gpu_load_u32(y+i*4)));i=i+1;}}
    else {let row=vk_quotient(index,n);let col=vk_remainder(index,n);
        while i<m {sum=vk_add(sum,vk_mul(gpu_load_u32(a+(i*k+row)*4),gpu_load_u32(g+(i*n+col)*4)));i=i+1;}}
    return sum;
}
fn ptg_convolution(index,a,w,g,meta,role,first,last) {
    let batch=gpu_load_u64(meta+64);let cout=gpu_load_u64(meta+72);let oh=gpu_load_u64(meta+80);let ow=gpu_load_u64(meta+88);
    let cin=gpu_load_u64(meta+104);let ih=gpu_load_u64(meta+112);let iw=gpu_load_u64(meta+120);
    let k=gpu_load_u64(meta+160);let stride=gpu_load_u64(meta+168);let pad=gpu_load_u64(meta+176);let sum=0;
    if role==3 {let b=first;while b<last {let p=0;while p<oh*ow {sum=vk_add(sum,gpu_load_u32(g+((b*cout+index)*oh*ow+p)*4));p=p+1;}b=b+1;}return sum;}
    if role==2 {
        let kx=vk_remainder(index,k);let ky=vk_remainder(vk_quotient(index,k),k);
        let ci=vk_remainder(vk_quotient(index,k*k),cin);let co=vk_quotient(index,cin*k*k);let b=first;
        // Unpadded windows stay inside the input: walk rows by pointer, four loads before the adds.
        if !pad {while b<last {let source=a+(((b*cin+ci)*ih+ky)*iw+kx)*4;let target=g+(b*cout+co)*oh*ow*4;let y=0;
                while y<oh {let row=source+y*stride*iw*4;let x=0;
                    while x+4<=ow {let a0=gpu_load_u32(row+x*stride*4);let a1=gpu_load_u32(row+(x+1)*stride*4);let a2=gpu_load_u32(row+(x+2)*stride*4);let a3=gpu_load_u32(row+(x+3)*stride*4);
                        let g0=gpu_load_u32(target+x*4);let g1=gpu_load_u32(target+x*4+4);let g2=gpu_load_u32(target+x*4+8);let g3=gpu_load_u32(target+x*4+12);
                        sum=vk_add(sum,vk_mul(a0,g0));sum=vk_add(sum,vk_mul(a1,g1));sum=vk_add(sum,vk_mul(a2,g2));sum=vk_add(sum,vk_mul(a3,g3));x=x+4;}
                    while x<ow {sum=vk_add(sum,vk_mul(gpu_load_u32(row+x*stride*4),gpu_load_u32(target+x*4)));x=x+1;}target=target+ow*4;y=y+1;}
                b=b+1;}return sum;}
        while b<last {let y=0;while y<oh {let iy=y*stride+ky-pad;let x=0;
            while x<ow {let ix=x*stride+kx-pad;if iy>=0 && iy<ih && ix>=0 && ix<iw {
                sum=vk_add(sum,vk_mul(gpu_load_u32(a+((b*cin+ci)*ih*iw+iy*iw+ix)*4),gpu_load_u32(g+((b*cout+co)*oh*ow+y*ow+x)*4)));}x=x+1;}y=y+1;}b=b+1;}
    } else {
        let ix=vk_remainder(index,iw);let iy=vk_remainder(vk_quotient(index,iw),ih);
        let ci=vk_remainder(vk_quotient(index,ih*iw),cin);let b=vk_quotient(index,cin*ih*iw);let co=0;
        // Only output positions whose kernels cover this input can contribute.
        // Descending output coordinates retain ascending kernel-offset sum order.
        let ylow=0;let xlow=0;if iy+pad>=k {ylow=vk_quotient(iy+pad-k+stride,stride);}if ix+pad>=k {xlow=vk_quotient(ix+pad-k+stride,stride);}
        let yhigh=vk_quotient(iy+pad,stride);let xhigh=vk_quotient(ix+pad,stride);if yhigh>=oh {yhigh=oh-1;}if xhigh>=ow {xhigh=ow-1;}
        let filter=w+ci*k*k*4;let plane=g+b*cout*oh*ow*4;
        while co<cout {let y=yhigh;while y>=ylow {let weights=filter+(iy+pad-y*stride)*k*4;let gradient=plane+y*ow*4;let x=xhigh;
            while x>=xlow {sum=vk_add(sum,vk_mul(gpu_load_u32(weights+(ix+pad-x*stride)*4),gpu_load_u32(gradient+x*4)));x=x-1;}y=y-1;}filter=filter+cin*k*k*4;plane=plane+oh*ow*4;co=co+1;}
    }return sum;
}
fn kernel(index,input,output,count) {
    if index>=count {return 0;}
    let mode=gpu_launch_word(0);let a=gpu_launch_word(1);let b=gpu_launch_word(2);let meta=gpu_launch_word(3);
    if mode==100 {gpu_store_u32(output+index*4,0);return 0;}
    if mode==103 {gpu_store_u32(output+index*4,vk_div(gpu_f32_from_i64(load8(input+index)),0x437f0000));return 0;}
    if mode==104 {
        let source=index;let frame=vk_quotient(index,21168);let item=vk_remainder(frame,a);
        if (b>>item)&1 {source=index+83-2*vk_remainder(index,84);}
        gpu_store_u32(output+index*4,vk_div(gpu_f32_from_i64(load8(input+source)),0x437f0000));return 0;
    }
    if mode==105 {
        let source=index;let frame=vk_quotient(index,49152);let item=vk_remainder(frame,a);
        if (b>>item)&1 {source=index+127-2*vk_remainder(index,128);}
        gpu_store_u32(output+index*4,vk_div(gpu_f32_from_i64(load8(input+source)),0x437f0000));return 0;
    }
    // Convolution weight and bias gradients split the batch into 64 slices, then
    // add the slices in a fixed order, keeping the reduction deterministic.
    if mode==106 {
        let n=vk_quotient(count,64);let part=vk_quotient(index,n);let batch=gpu_load_u64(meta+64);let chunk=vk_quotient(batch+63,64);let first=part*chunk;let last=first+chunk;if last>batch {last=batch;}if first>last {first=last;}
        gpu_store_u32(output+index*4,ptg_convolution(vk_remainder(index,n),a,0,input,meta,b,first,last));return 0;
    }
    if mode==107 {let parts=b;if !parts {parts=64;}let sum=0;let part=0;while part<parts {sum=vk_add(sum,gpu_load_u32(input+(part*count+index)*4));part=part+1;}gpu_store_u32(output+index*4,vk_add(gpu_load_u32(output+index*4),sum));return 0;}
    // Matrix input gradients read a transposed weight copy, so a warp's weight loads are contiguous.
    if mode==113 {let n=gpu_load_u64(meta+88);let k=gpu_load_u64(meta+120);let i=vk_quotient(index,k);gpu_store_u32(output+index*4,gpu_load_u32(a+((index-i*k)*n+i)*4));return 0;}
    if mode==112 {let n=gpu_load_u64(meta+88);let k=gpu_load_u64(meta+120);let row=vk_quotient(index,k);let col=index-row*k;let x=input+row*n*4;let sum=0;let i=0;
        while i+8<=n {let x0=gpu_load_u32(x+(i+0)*4);let y0=gpu_load_u32(b+((i+0)*k+col)*4);let x1=gpu_load_u32(x+(i+1)*4);let y1=gpu_load_u32(b+((i+1)*k+col)*4);let x2=gpu_load_u32(x+(i+2)*4);let y2=gpu_load_u32(b+((i+2)*k+col)*4);let x3=gpu_load_u32(x+(i+3)*4);let y3=gpu_load_u32(b+((i+3)*k+col)*4);let x4=gpu_load_u32(x+(i+4)*4);let y4=gpu_load_u32(b+((i+4)*k+col)*4);let x5=gpu_load_u32(x+(i+5)*4);let y5=gpu_load_u32(b+((i+5)*k+col)*4);let x6=gpu_load_u32(x+(i+6)*4);let y6=gpu_load_u32(b+((i+6)*k+col)*4);let x7=gpu_load_u32(x+(i+7)*4);let y7=gpu_load_u32(b+((i+7)*k+col)*4);sum=vk_add(sum,vk_mul(x0,y0));sum=vk_add(sum,vk_mul(x1,y1));sum=vk_add(sum,vk_mul(x2,y2));sum=vk_add(sum,vk_mul(x3,y3));sum=vk_add(sum,vk_mul(x4,y4));sum=vk_add(sum,vk_mul(x5,y5));sum=vk_add(sum,vk_mul(x6,y6));sum=vk_add(sum,vk_mul(x7,y7));i=i+8;}
        while i<n {sum=vk_add(sum,vk_mul(gpu_load_u32(x+i*4),gpu_load_u32(b+(i*k+col)*4)));i=i+1;}gpu_store_u32(output+index*4,vk_add(gpu_load_u32(output+index*4),sum));return 0;}
    // Unpadded convolution gradients in blocks of 8 channels: input gradients share each
    // output-gradient load across input channels, weight partials share each
    // activation across output channels. Every value keeps its own summation order.
    if mode==114 || mode==115 {
        let cout=gpu_load_u64(meta+72);let oh=gpu_load_u64(meta+80);let ow=gpu_load_u64(meta+88);let cin=gpu_load_u64(meta+104);let ih=gpu_load_u64(meta+112);let iw=gpu_load_u64(meta+120);
        let k=gpu_load_u64(meta+160);let stride=gpu_load_u64(meta+168);let plane=ih*iw*4;let s0=0;let s1=0;let s2=0;let s3=0;let s4=0;let s5=0;let s6=0;let s7=0;
        if mode==114 {
            let ix=vk_remainder(index,iw);let iy=vk_remainder(vk_quotient(index,iw),ih);let groups=vk_quotient(cin,8);let first=vk_remainder(vk_quotient(index,ih*iw),groups)*8;let batch=vk_quotient(index,ih*iw*groups);
            let ylow=0;let xlow=0;if iy>=k {ylow=vk_quotient(iy-k+stride,stride);}if ix>=k {xlow=vk_quotient(ix-k+stride,stride);}
            let yhigh=vk_quotient(iy,stride);let xhigh=vk_quotient(ix,stride);if yhigh>=oh {yhigh=oh-1;}if xhigh>=ow {xhigh=ow-1;}
            let kk=k*k*4;let filter=b+first*kk;let gradient=input+batch*cout*oh*ow*4;let co=0;
            while co<cout {let y=yhigh;while y>=ylow {let weights=filter+(iy-y*stride)*k*4;let row=gradient+y*ow*4;let x=xhigh;
                    while x>=xlow {let value=gpu_load_u32(row+x*4);let kx=ix-x*stride;s0=vk_add(s0,vk_mul(gpu_load_u32(weights+0*kk+kx*4),value));s1=vk_add(s1,vk_mul(gpu_load_u32(weights+1*kk+kx*4),value));s2=vk_add(s2,vk_mul(gpu_load_u32(weights+2*kk+kx*4),value));s3=vk_add(s3,vk_mul(gpu_load_u32(weights+3*kk+kx*4),value));s4=vk_add(s4,vk_mul(gpu_load_u32(weights+4*kk+kx*4),value));s5=vk_add(s5,vk_mul(gpu_load_u32(weights+5*kk+kx*4),value));s6=vk_add(s6,vk_mul(gpu_load_u32(weights+6*kk+kx*4),value));s7=vk_add(s7,vk_mul(gpu_load_u32(weights+7*kk+kx*4),value));x=x-1;}y=y-1;}filter=filter+cin*kk;gradient=gradient+oh*ow*4;co=co+1;}
            let out=output+(((batch*cin+first)*ih+iy)*iw+ix)*4;gpu_store_u32(out+0*plane,vk_add(gpu_load_u32(out+0*plane),s0));gpu_store_u32(out+1*plane,vk_add(gpu_load_u32(out+1*plane),s1));gpu_store_u32(out+2*plane,vk_add(gpu_load_u32(out+2*plane),s2));gpu_store_u32(out+3*plane,vk_add(gpu_load_u32(out+3*plane),s3));gpu_store_u32(out+4*plane,vk_add(gpu_load_u32(out+4*plane),s4));gpu_store_u32(out+5*plane,vk_add(gpu_load_u32(out+5*plane),s5));gpu_store_u32(out+6*plane,vk_add(gpu_load_u32(out+6*plane),s6));gpu_store_u32(out+7*plane,vk_add(gpu_load_u32(out+7*plane),s7));return 0;
        }
        let parts=b;let n=vk_quotient(count,parts);let part=vk_quotient(index,n);let item=index-part*n;let kx=vk_remainder(item,k);let ky=vk_remainder(vk_quotient(item,k),k);let ci=vk_remainder(vk_quotient(item,k*k),cin);let first=vk_quotient(item,cin*k*k)*8;let rest=item-vk_quotient(item,cin*k*k)*cin*k*k;
        let batch=gpu_load_u64(meta+64);let chunk=vk_quotient(batch+parts-1,parts);let bb=part*chunk;let last=bb+chunk;if last>batch {last=batch;}plane=oh*ow*4;
        while bb<last {let source=a+(((bb*cin+ci)*ih+ky)*iw+kx)*4;let target=input+(bb*cout+first)*oh*ow*4;let y=0;
            while y<oh {let row=source+y*stride*iw*4;let x=0;while x<ow {let value=gpu_load_u32(row+x*stride*4);s0=vk_add(s0,vk_mul(value,gpu_load_u32(target+0*plane+x*4)));s1=vk_add(s1,vk_mul(value,gpu_load_u32(target+1*plane+x*4)));s2=vk_add(s2,vk_mul(value,gpu_load_u32(target+2*plane+x*4)));s3=vk_add(s3,vk_mul(value,gpu_load_u32(target+3*plane+x*4)));s4=vk_add(s4,vk_mul(value,gpu_load_u32(target+4*plane+x*4)));s5=vk_add(s5,vk_mul(value,gpu_load_u32(target+5*plane+x*4)));s6=vk_add(s6,vk_mul(value,gpu_load_u32(target+6*plane+x*4)));s7=vk_add(s7,vk_mul(value,gpu_load_u32(target+7*plane+x*4)));x=x+1;}target=target+ow*4;y=y+1;}bb=bb+1;}
        gpu_store_u32(output+((part*cout+first+0)*cin*k*k+rest)*4,s0);gpu_store_u32(output+((part*cout+first+1)*cin*k*k+rest)*4,s1);gpu_store_u32(output+((part*cout+first+2)*cin*k*k+rest)*4,s2);gpu_store_u32(output+((part*cout+first+3)*cin*k*k+rest)*4,s3);gpu_store_u32(output+((part*cout+first+4)*cin*k*k+rest)*4,s4);gpu_store_u32(output+((part*cout+first+5)*cin*k*k+rest)*4,s5);gpu_store_u32(output+((part*cout+first+6)*cin*k*k+rest)*4,s6);gpu_store_u32(output+((part*cout+first+7)*cin*k*k+rest)*4,s7);return 0;
    }
    if mode==111 {let width=gpu_load_u64(meta+8);let size=width*3;let k=vk_quotient(index,width);gpu_store_u32(output+index*4,gpu_load_u32(a+((index-k*width)*size+k)*4));return 0;}
    if mode==109 || mode==110 {
        let batch=gpu_load_u64(meta);let width=gpu_load_u64(meta+8);let rows=gpu_load_u64(meta+16)*batch;let gates=gpu_load_u64(meta+40);let size=width*3;let sum=0;
        if mode==109 {let i=vk_quotient(index,size);let k=vk_remainder(index,size);let row=batch;while row<rows {sum=vk_add(sum,vk_mul(gpu_load_u32(a+((row-batch)*width+i)*4),gpu_load_u32(gates+(row*size+k)*4)));row=row+1;}}
        else {let row=0;while row<rows {sum=vk_add(sum,gpu_load_u32(gates+(row*size+index)*4));row=row+1;}}
        gpu_store_u32(output+index*4,vk_add(gpu_load_u32(output+index*4),sum));return 0;
    }
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
    else if op==12 {value=ptg_convolution(index,a,b,input,meta,role,0,gpu_load_u64(meta+64));}
    gpu_store_u32(output+index*4,vk_add(gpu_load_u32(output+index*4),value));return 0;
}
fn main() {return 78;}
