// Packed FP32 operations shared by the native CPU and HIP inference backends.
import "../../core/packed.flex";
lowering vk_add "f32.add";
lowering vk_sub "f32.sub";
lowering vk_mul "f32.mul";
lowering vk_div "f32.div";
fn vk_add(a,b) {return pb_f64_to_f32(f64_add(pb_f32_to_f64(a),pb_f32_to_f64(b)));}
fn vk_sub(a,b) {return pb_f64_to_f32(f64_sub(pb_f32_to_f64(a),pb_f32_to_f64(b)));}
fn vk_mul(a,b) {return pb_f64_to_f32(f64_mul(pb_f32_to_f64(a),pb_f32_to_f64(b)));}
fn vk_div(a,b) {return pb_f64_to_f32(f64_div(pb_f32_to_f64(a),pb_f32_to_f64(b)));}
fn vk_max(a,b) {if (a^b)&0x80000000 {if a&0x80000000 {return b;}return a;}if a&0x80000000 {if a<b {return a;}return b;}if a>b {return a;}return b;}
// Range reduction followed by a degree-seven polynomial on [-ln(2)/2,ln(2)/2].
// Both backends use the same operation order, without FMA reassociation.
fn vk_exp(x) {
    x=vk_max(0xc2a00000,x);if vk_max(x,0x42a00000)==x {x=0x42a00000;}
    let scaled=vk_mul(x,0x3fb8aa3b);let n=f64_to_i64_round(pb_f32_to_f64(scaled));
    let r=vk_sub(x,vk_mul(pb_f64_to_f32(f64_from_i64(n)),0x3f317218));
    let p=0x39500d01;p=vk_add(0x3ab60b61,vk_mul(p,r));p=vk_add(0x3c088889,vk_mul(p,r));
    p=vk_add(0x3d2aaaab,vk_mul(p,r));p=vk_add(0x3e2aaaab,vk_mul(p,r));p=vk_add(0x3f000000,vk_mul(p,r));
    p=vk_add(0x3f800000,vk_mul(p,r));p=vk_add(0x3f800000,vk_mul(p,r));return vk_mul(p,(n+127)<<23);
}
fn vk_sigmoid(x) {let e=vk_exp((x&0x7fffffff)|0x80000000);let d=vk_add(0x3f800000,e);if x&0x80000000 {return vk_div(e,d);}return vk_div(0x3f800000,d);}
fn vk_broadcast(index,shape,source) {let result=0;let stride=1;let i=4;while i {i=i-1;let d=load64(shape+i*8);let s=load64(source+i*8);if s!=1 {result=result+(index%d)*stride;}index=index/d;stride=stride*s;}return result;}
fn vk_element(index,a,b,weights,bias,meta) {
    let op=load64(meta);let out=meta+64;let ashape=meta+96;let bshape=meta+128;let p=meta+160;
    if op>=3 && op<=7 {let x=pb_u32(a+vk_broadcast(index,out,ashape)*4);let y=pb_u32(b+vk_broadcast(index,out,bshape)*4);if op==3 {return vk_add(x,y);}if op==4 {return vk_sub(x,y);}if op==5 {return vk_mul(x,y);}if op==6 {return vk_div(x,y);}return vk_max(x,y);}
    if op==24 {return vk_sigmoid(pb_u32(a+index*4));}
    if op==10 {let at=index;let result=0;let i=4;while i {i=i-1;let d=load64(out+i*8);let axis=load64(p+i*8);let stride=1;let j=axis+1;while j<4 {stride=stride*load64(ashape+j*8);j=j+1;}result=result+(at%d)*stride;at=at/d;}return pb_u32(a+result*4);}
    if op==25 || op==26 {let axis=load64(p);let inner=1;let i=axis+1;while i<4 {inner=inner*load64(out+i*8);i=i+1;}let dim=load64(out+axis*8);let coordinate=(index/inner)%dim;let outer=index/(inner*dim);let size=load64(ashape+axis*8);let source=a;
        if op==26 {coordinate=coordinate+load64(p+8);}else if coordinate>=size {coordinate=coordinate-size;size=load64(bshape+axis*8);source=b;}
        return pb_u32(source+((outer*size+coordinate)*inner+index%inner)*4);
    }
    if op==27 {let ow=load64(out+24);let oh=load64(out+16);let iw=load64(ashape+24);let ih=load64(ashape+16);let scale=load64(p);let src=((index/(ow*oh))*ih+(index/ow)%oh/scale)*iw+index%ow/scale;return pb_u32(a+src*4);}
    if op==28 {let axis=load64(p);let inner=1;let i=axis+1;while i<4 {inner=inner*load64(out+i*8);i=i+1;}let length=load64(out+axis*8);let start=index-((index/inner)%length)*inner;let maximum=0xff800000;i=0;while i<length {maximum=vk_max(maximum,pb_u32(a+(start+i*inner)*4));i=i+1;}let sum=0;i=0;while i<length {sum=vk_add(sum,vk_exp(vk_sub(pb_u32(a+(start+i*inner)*4),maximum)));i=i+1;}return vk_div(vk_exp(vk_sub(pb_u32(a+index*4),maximum)),sum);}
    if op==29 {let m=load64(out+16);let n=load64(out+24);let k=load64(ashape+24);let batch=index/(m*n);let row=(index/n)%m;let col=index%n;let sum=0;let i=0;while i<k {sum=vk_add(sum,vk_mul(pb_u32(a+((batch*m+row)*k+i)*4),pb_u32(b+((batch*k+i)*n+col)*4)));i=i+1;}return sum;}
    if op==12 || op==14 {
        let cin=load64(ashape+8);let ih=load64(ashape+16);let iw=load64(ashape+24);let cout=load64(out+8);let oh=load64(out+16);let ow=load64(out+24);
        let k=load64(p);let stride=load64(p+8);let pad=load64(p+16);let groups=load64(p+24);let ox=index%ow;let oy=(index/ow)%oh;let channel=(index/(ow*oh))%cout;let batch=index/(ow*oh*cout);let sum=0;
        let first=0;let channels=cin/groups;if op==14 {first=channel;channels=1;sum=0xff800000;}else {first=(channel/(cout/groups))*channels;}
        let ci=0;while ci<channels {let y=0;while y<k {let iy=oy*stride+y-pad;let x=0;while x<k {let ix=ox*stride+x-pad;
            if iy>=0 && iy<ih && ix>=0 && ix<iw {let v=pb_u32(a+(((batch*cin+first+ci)*ih+iy)*iw+ix)*4);if op==14 {sum=vk_max(sum,v);}else {let w=pb_u32(weights+(((channel*channels+ci)*k+y)*k+x)*4);sum=vk_add(sum,vk_mul(v,w));}}x=x+1;}y=y+1;}ci=ci+1;}
        if bias {sum=vk_add(sum,pb_u32(bias+channel*4));}return sum;
    }
    return 0x7fc00000;
}
