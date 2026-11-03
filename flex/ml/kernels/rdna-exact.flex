// Correctly rounded FP32 divide and square root for the direct RDNA encoder,
// which has neither, and index arithmetic without its missing integer/float
// conversions (the generic path emulates them in software f64). Results match PTX div.rn/sqrt.rn bit for bit: an SFU
// estimate is corrected with exact integer arithmetic, then rounded to nearest even.
fn vr_mantissa(bits) {let e=(bits>>23)&255;if e {return (bits&0x7fffff)|0x800000;}let m=bits&0x7fffff;while m<0x800000 {m=m<<1;}return m;}
fn vr_exponent(bits) {let e=(bits>>23)&255;if e {return e-127;}let m=bits&0x7fffff;e=-126;while m<0x800000 {m=m<<1;e=e-1;}return e;}
// Scale an FP32 value in [0.5,4) to an integer: value * 2^shift.
fn vr_scaled(bits,shift) {let m=(bits&0x7fffff)|0x800000;let k=((bits>>23)&255)-127+shift-23;if k>=0 {return m<<k;}return m>>(0-k);}
fn vk_div_exact(a,b) {
    let sign=(a^b)&0x80000000;let ea=(a>>23)&255;let eb=(b>>23)&255;let fa=a&0x7fffff;let fb=b&0x7fffff;
    if ea==255 && fa {return a|0x400000;}if eb==255 && fb {return b|0x400000;}
    if ea==255 {if eb==255 {return 0x7fffffff;}return sign|0x7f800000;}if eb==255 {return sign;}
    if !eb && !fb {if !ea && !fa {return 0x7fffffff;}return sign|0x7f800000;}if !ea && !fa {return sign;}
    let ma=vr_mantissa(a);let mb=vr_mantissa(b);let exponent=vr_exponent(a)-vr_exponent(b);let n=ma<<23;let shift=23;
    if ma<mb {n=ma<<24;shift=24;exponent=exponent-1;}
    // Quotient estimate from mantissas in [1,2), then the exact truncated quotient q and remainder.
    let q=vr_scaled(vk_mul(0x3f800000|(ma&0x7fffff),gpu_f32_rcp_approx(0x3f800000|(mb&0x7fffff))),shift);let remainder=n-q*mb;
    while remainder<0 {q=q-1;remainder=remainder+mb;}while remainder>=mb {q=q+1;remainder=remainder-mb;}
    if exponent< -126 {
        let d=-126-exponent;if d>=25 {return sign;}let kept=q>>d;let low=(q&((1<<d)-1))*mb+remainder;let half=(1<<(d-1))*mb;
        if low>half || (low==half && (kept&1)) {kept=kept+1;}return sign|kept;
    }
    if remainder*2>mb || (remainder*2==mb && (q&1)) {q=q+1;}if q==0x1000000 {q=0x800000;exponent=exponent+1;}
    if exponent>127 {return sign|0x7f800000;}return sign|((exponent+127)<<23)|(q&0x7fffff);
}
fn vk_sqrt_exact(x) {
    let e=(x>>23)&255;let f=x&0x7fffff;
    if e==255 {if f {return x|0x400000;}if x&0x80000000 {return 0x7fffffff;}return x;}
    if !e && !f {return x;}if x&0x80000000 {return 0x7fffffff;}
    // x = m * 2^(exponent-23) with an even exponent, so sqrt(x) = sqrt(m * 2^23) * 2^(exponent/2-23).
    let m=vr_mantissa(x);let exponent=vr_exponent(x);if exponent&1 {m=m<<1;exponent=exponent-1;}let n=m<<23;
    let v=0x3f800000|(m&0x7fffff);if m>=0x1000000 {v=0x40000000|((m>>1)&0x7fffff);}
    let y=0x5f3759df-(v>>1);let i=0;
    while i<3 {y=vk_mul(y,vk_sub(0x3fc00000,vk_mul(vk_mul(0x3f000000,v),vk_mul(y,y))));i=i+1;}
    let s=vr_scaled(vk_mul(v,y),23);while s*s>n {s=s-1;}while (s+1)*(s+1)<=n {s=s+1;}
    // An exact square root never lies halfway between two FP32 values.
    if n-s*s>s {s=s+1;}let half=((exponent+300)>>1)-150;if s==0x1000000 {s=0x800000;half=half+1;}
    return ((half+127)<<23)|(s&0x7fffff);
}
// Exact FP32 value of 0 <= x < 2^24, built from integer bits: 2^23+x has ulp 1.
fn vr_index_f32(x) {if x<0x800000 {return vk_sub(0x4b000000|x,0x4b000000);}let half=vk_sub(0x4b000000|(x>>1),0x4b000000);return vk_add(vk_add(half,half),(0-(x&1))&0x3f800000);}
// Indices below 2^24 (the generic quotient's own bound): a rounded FP32 estimate
// below 2^23, then the same exact integer correction.
fn vk_quotient(a,b) {
    if b==1 {return a;}if a<0 || a>=0x1000000 || b<2 || b>=0x1000000 {return vk_quotient_f64(a,b);}
    let q=vk_add(vk_mul(vr_index_f32(a),gpu_f32_rcp_approx(vr_index_f32(b))),0x4b000000)-0x4b000000;let remainder=a-q*b;
    while remainder<0 {q=q-1;remainder=remainder+b;}while remainder>=b {q=q+1;remainder=remainder-b;}return q;
}
