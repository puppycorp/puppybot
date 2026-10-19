// Derived from rust-lang/libm 0.2.16 (MIT), musl/FreeBSD math routines.
// Copyright (c) 2018 Jorge Aparicio; Copyright © 2005-2020 Rich Felker, et al.
// Atan/atan2: Copyright (C) 1993 Sun Microsystems, Inc. All rights reserved.
// Exp: Copyright (C) 2004 Sun Microsystems, Inc. All rights reserved.
// Permission to use, copy, modify, and distribute this software is freely
// granted, provided that the Sun notices are preserved. See f64-math.LICENSE.
// Modified: binary64 arithmetic/operation order over portable i64 words.
import "f64.flex";
fn f64_math_neg(a) {return a^(-9223372036854775807-1);}
fn f64_math_square_low(x,hi) {
	let xc=f64_mul(x,4728779608772575232);let xh=f64_add(f64_sub(x,xc),xc);let xl=f64_sub(x,xh);
	return f64_add(f64_add(f64_sub(f64_mul(xh,xh),hi),f64_mul(f64_mul(4611686018427387904,xh),xl)),f64_mul(xl,xl));
}
fn f64_hypot(x,y) {
	x=f64_magnitude(x);y=f64_magnitude(y);if x<y {let t=x;x=y;y=t;}
	let ex=x>>52;let ey=y>>52;
	if ey==2047 {return y;}if ex==2047 || y==0 {return x;}
	if ex-ey>64 {return f64_add(x,y);}
	let z=4607182418800017408;
	if ex>1533 {z=0x6bb0000000000000;x=f64_mul(x,0x1430000000000000);y=f64_mul(y,0x1430000000000000);}
	else if ey<573 {z=0x1430000000000000;x=f64_mul(x,0x6bb0000000000000);y=f64_mul(y,0x6bb0000000000000);}
	let hx=f64_mul(x,x);let lx=f64_math_square_low(x,hx);let hy=f64_mul(y,y);let ly=f64_math_square_low(y,hy);
	return f64_mul(z,f64_sqrt(f64_add(f64_add(f64_add(ly,lx),hy),hx)));
}
fn f64_math_atanhi(i) {
	if i==0 {return 4602023952714414927;}
	if i==1 {return 4605249457297304856;}
	if i==2 {return 4607027438436873883;}
	if i==3 {return 4609753056924675352;}
	return 0;
}
fn f64_math_atanlo(i) {
	if i==0 {return 4357843414468748770;}
	if i==1 {return 4359948597267291143;}
	if i==2 {return 4354989122426817469;}
	if i==3 {return 4364452196894661639;}
	return 0;
}
fn f64_math_at(i) {
	if i==0 {return 4599676419421066509;}
	if i==1 {return -4626998257160492092;}
	if i==2 {return 4594314991288484863;}
	if i==3 {return -4630701217362536847;}
	if i==4 {return 4591215095208222830;}
	if i==5 {return -4633165035261879699;}
	if i==6 {return 4589464229703073105;}
	if i==7 {return -4634804155249132134;}
	if i==8 {return 4587333258118041067;}
	if i==9 {return -4637946461342241745;}
	if i==10 {return 4580351289466214929;}
	return 0;
}
fn f64_atan(x) {
	let ix=(x>>32)&4294967295;let sign=ix>>31;ix=ix&2147483647;
	if ix>=0x44100000 {if f64_is_nan(x) {return x;}let z=f64_add(f64_math_atanhi(3),0x03800000);if sign!=0 {return f64_math_neg(z);}return z;}
	let id=-1;
	if ix<0x3fdc0000 {if ix<0x3e400000 {return x;}}
	else {
		x=f64_magnitude(x);
		if ix<0x3ff30000 {
			if ix<0x3fe60000 {x=f64_div(f64_sub(f64_mul(4611686018427387904,x),4607182418800017408),f64_add(4611686018427387904,x));id=0;}
			else {x=f64_div(f64_sub(x,4607182418800017408),f64_add(x,4607182418800017408));id=1;}
		}else if ix<0x40038000 {x=f64_div(f64_sub(x,4609434218613702656),f64_add(4607182418800017408,f64_mul(4609434218613702656,x)));id=2;}
		else {x=f64_div(-4616189618054758400,x);id=3;}
	}
	let z=f64_mul(x,x);let w=f64_mul(z,z);
	let odd=f64_add(f64_math_at(8),f64_mul(w,f64_math_at(10)));
	odd=f64_add(f64_math_at(6),f64_mul(w,odd));odd=f64_add(f64_math_at(4),f64_mul(w,odd));odd=f64_add(f64_math_at(2),f64_mul(w,odd));odd=f64_add(f64_math_at(0),f64_mul(w,odd));let s1=f64_mul(z,odd);
	let even=f64_add(f64_math_at(7),f64_mul(w,f64_math_at(9)));
	even=f64_add(f64_math_at(5),f64_mul(w,even));even=f64_add(f64_math_at(3),f64_mul(w,even));even=f64_add(f64_math_at(1),f64_mul(w,even));let s2=f64_mul(w,even);
	if id<0 {return f64_sub(x,f64_mul(x,f64_add(s1,s2)));}
	let result=f64_sub(f64_math_atanhi(id),f64_sub(f64_sub(f64_mul(x,f64_add(s1,s2)),f64_math_atanlo(id)),x));
	if sign!=0 {return f64_math_neg(result);}return result;
}
fn f64_atan2(y,x) {
	if f64_is_nan(y) {return y|2251799813685248;}if f64_is_nan(x) {return x|2251799813685248;}
	let ix=(x>>32)&4294967295;let lx=x&4294967295;let iy=(y>>32)&4294967295;let ly=y&4294967295;
	if (((ix-0x3ff00000)&4294967295)|lx)==0 {return f64_atan(y);}
	let m=((iy>>31)&1)|((ix>>30)&2);ix=ix&2147483647;iy=iy&2147483647;
	if (iy|ly)==0 {if m<2 {return y;}if m==2 {return 4614256656552045848;}return -4609115380302729960;}
	if (ix|lx)==0 {if (m&1)!=0 {return -4613618979930100456;}return 4609753056924675352;}
	if ix==0x7ff00000 {
		if iy==0x7ff00000 {if m==0 {return 4605249457297304856;}if m==1 {return -4618122579557470952;}if m==2 {return 4612488097114038738;}return -4610883939740737070;}
		if m==0 {return 0;}if m==1 {return (-9223372036854775807-1);}if m==2 {return 4614256656552045848;}return -4609115380302729960;
	}
	if ((ix+(64<<20))&4294967295)<iy || iy==0x7ff00000 {if (m&1)!=0 {return -4613618979930100456;}return 4609753056924675352;}
	let z=0;if !((m&2)!=0 && ((iy+(64<<20))&4294967295)<ix) {z=f64_atan(f64_magnitude(f64_div(y,x)));}
	if m==0 {return z;}if m==1 {return f64_math_neg(z);}if m==2 {return f64_sub(4614256656552045848,f64_sub(z,4368955796522032135));}
	return f64_sub(f64_sub(z,4368955796522032135),4614256656552045848);
}
fn f64_scalbn(x,n) {
	if f64_is_nan(x) {return x|2251799813685248;}
	if n>1023 {x=f64_mul(x,0x7fe0000000000000);n=n-1023;if n>1023 {x=f64_mul(x,0x7fe0000000000000);n=n-1023;if n>1023 {n=1023;}}}
	else if n<(-1022) {x=f64_mul(x,0x0360000000000000);n=n+969;if n<(-1022) {x=f64_mul(x,0x0360000000000000);n=n+969;if n<(-1022) {n=-1022;}}}
	return f64_mul(x,(1023+n)<<52);
}
fn f64_exp(x) {
	let hx=(x>>32)&4294967295;let sign=hx>>31;hx=hx&2147483647;
	if hx>=0x4086232b {
		if f64_is_nan(x) {return x;}
		if f64_gt(x,4649454530587146735) {return f64_mul(x,0x7fe0000000000000);}
		if f64_lt(x,-4573606559926636463) {return 0;}
	}
	let hi=0;let lo=0;let k=0;
	if hx>0x3fd62e42 {
		if hx>=0x3ff0a2b2 {let half=4602678819172646912;if sign!=0 {half=-4620693217682128896;}k=f64_to_i64_trunc(f64_add(f64_mul(4609176140021203710,x),half));}
		else {k=1-sign-sign;}
		let fk=f64_from_i64(k);hi=f64_sub(x,f64_mul(fk,4604418534311723008));lo=f64_mul(fk,4461442080421002358);x=f64_sub(hi,lo);
	}else if hx>0x3e300000 {hi=x;}
	else {return f64_add(4607182418800017408,x);}
	let xx=f64_mul(x,x);
	let p=f64_add(-4702957295668925455,f64_mul(xx,4496342204012209360));
	p=f64_add(4544508515198557740,f64_mul(xx,p));p=f64_add(-4654820494858601069,f64_mul(xx,p));p=f64_add(4595172819793696062,f64_mul(xx,p));
	let c=f64_sub(x,f64_mul(xx,p));let y=f64_add(4607182418800017408,f64_add(f64_sub(f64_div(f64_mul(x,c),f64_sub(4611686018427387904,c)),lo),hi));
	if k==0 {return y;}return f64_scalbn(y,k);
}

// Trig reduction derived from rem_pio2/k_sin/k_cos/sin/cos, same Sun notice.
// Supported finite range: abs(x) high word < 0x413921fb. Large Payne-Hanek
// reduction remains deliberately unsupported; query f64_trig_supported first.
fn f64_trig_supported(x) {if ((x>>32)&2147483647)<0x413921fb {return 1;}return 0;}
fn f64_math_invalid(x) {if f64_is_nan(x) {return x|2251799813685248;}return -2251799813685248;}
fn f64_math_sin_kernel(x,y,iy) {
 let z=f64_mul(x,x);let w=f64_mul(z,z);
 let r=f64_add(f64_add(4575957461383575718,f64_mul(z,f64_add(-4671919876304969259,f64_mul(z,4523617212983017085)))),f64_mul(f64_mul(z,w),f64_add(-4730215680275931925,f64_mul(z,4460209850635244924))));let v=f64_mul(z,x);
 if iy==0 {return f64_add(x,f64_mul(v,f64_add(-4628199217061079735,f64_mul(z,r))));}
 return f64_sub(x,f64_sub(f64_sub(f64_mul(z,f64_sub(f64_mul(4602678819172646912,y),f64_mul(v,r))),y),f64_mul(v,-4628199217061079735)));
}
fn f64_math_cos_kernel(x,y) {
 let z=f64_mul(x,x);let w=f64_mul(z,z);
 let r=f64_add(f64_mul(z,f64_add(4586165620538955084,f64_mul(z,f64_add(-4659324094485802633,f64_mul(z,4537941361668330896))))),f64_mul(f64_mul(w,w),f64_add(-4714566979978243411,f64_mul(z,f64_add(4477121870137962948,f64_mul(z,-4780295122622859052))))));
 let hz=f64_mul(4602678819172646912,z);w=f64_sub(4607182418800017408,hz);
 return f64_add(w,f64_add(f64_sub(f64_sub(4607182418800017408,w),hz),f64_sub(f64_mul(z,r),f64_mul(x,y))));
}
// field 0 returns integer quadrant count; fields 1/2 return binary64 tails.
// Pure word ABI intentionally recomputes reduction rather than shared scratch.
fn f64_math_reduce(x,field) {
 let ix=(x>>32)&2147483647;let sign=0;if x<0 {sign=1;}let n=0;let y0=0;let y1=0;let medium=1;
 if ix<=0x400f6a7a {
  if (ix&1048575)!=0x921fb {n=2;if ix<=0x4002d97c {n=1;}medium=0;}
 }else if ix<=0x401c463b {
  if ix<=0x4015fdbc {if ix!=0x4012d97c {n=3;medium=0;}}
  else if ix!=0x401921fb {n=4;medium=0;}
 }
 if medium==0 {
  let head=f64_mul(f64_from_i64(n),4609753056924401664);let tail=f64_mul(f64_from_i64(n),4454258360616903473);let z=0;
  if sign==0 {z=f64_sub(x,head);y0=f64_sub(z,tail);y1=f64_sub(f64_sub(z,y0),tail);}
  else {z=f64_add(x,head);y0=f64_add(z,tail);y1=f64_add(f64_sub(z,y0),tail);n=-n;}
 }else {
  let fnn=f64_sub(f64_add(f64_mul(x,4603909380684499075),4843621399236968448),4843621399236968448);n=f64_to_i64_trunc(fnn);
  let r=f64_sub(x,f64_mul(fnn,4609753056924401664));let w=f64_mul(fnn,4454258360616903473);y0=f64_sub(r,w);
  let ey=(y0>>52)&2047;let ex=ix>>20;
  if ex-ey>16 {let t=r;w=f64_mul(fnn,4454258360616747008);r=f64_sub(t,w);w=f64_sub(f64_mul(fnn,4297306550709743731),f64_sub(f64_sub(t,r),w));y0=f64_sub(r,w);ey=(y0>>52)&2047;
   if ex-ey>49 {t=r;w=f64_mul(fnn,4297306550709518336);r=f64_sub(t,w);w=f64_sub(f64_mul(fnn,4142048980368378305),f64_sub(f64_sub(t,r),w));y0=f64_sub(r,w);}
  }
  y1=f64_sub(f64_sub(r,y0),w);
 }
 if field==0 {return n;}if field==1 {return y0;}return y1;
}
fn f64_sin(x) {
 let ix=(x>>32)&2147483647;
 if ix<=0x3fe921fb {if ix<0x3e500000 {return x;}return f64_math_sin_kernel(x,0,0);}
 if ix>=0x7ff00000 {return f64_math_invalid(x);}
 if f64_trig_supported(x)==0 {return 0x7ff8000000000000;}
 let n=f64_math_reduce(x,0)&3;let y0=f64_math_reduce(x,1);let y1=f64_math_reduce(x,2);
 if n==0 {return f64_math_sin_kernel(y0,y1,1);}if n==1 {return f64_math_cos_kernel(y0,y1);}if n==2 {return f64_math_neg(f64_math_sin_kernel(y0,y1,1));}return f64_math_neg(f64_math_cos_kernel(y0,y1));
}
fn f64_cos(x) {
 let ix=(x>>32)&2147483647;
 if ix<=0x3fe921fb {if ix<0x3e46a09e {return 4607182418800017408;}return f64_math_cos_kernel(x,0);}
 if ix>=0x7ff00000 {return f64_math_invalid(x);}
 if f64_trig_supported(x)==0 {return 0x7ff8000000000000;}
 let n=f64_math_reduce(x,0)&3;let y0=f64_math_reduce(x,1);let y1=f64_math_reduce(x,2);
 if n==0 {return f64_math_cos_kernel(y0,y1);}if n==1 {return f64_math_neg(f64_math_sin_kernel(y0,y1,1));}if n==2 {return f64_math_neg(f64_math_cos_kernel(y0,y1));}return f64_math_sin_kernel(y0,y1,1);
}
