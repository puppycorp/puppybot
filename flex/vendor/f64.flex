// Portable IEEE 754 binary64 over signed i64 bit-pattern words. No host math.
// Arithmetic rounds to nearest, ties to even, after each operation. Subnormals
// are gradual, infinities and signed zeros follow IEEE, every NaN result is the
// positive canonical quiet NaN 0x7ff8000000000000. With NaN, eq/lt/le/gt/ge
// return false and ne returns true, matching IEEE unordered inequality.
// Integer conversions saturate (NaN -> 0); trunc drops fractional bits,
// nearest rounds ties to even, round rounds ties away from zero (Rust round).
// Bounded loops and limb intermediates keep this bootstrap-safe.
fn f64_sign(a) {return a&(-9223372036854775807-1);}
fn f64_magnitude(a) {return a&9223372036854775807;}
fn f64_exponent(a) {return (a>>52)&2047;}
fn f64_fraction(a) {return a&4503599627370495;}
fn f64_is_nan(a) {return f64_magnitude(a)>9218868437227405312;}
fn f64_is_finite(a) {return f64_exponent(a)!=2047;}
fn f64_nan() {return 9221120237041090560;}
fn f64_inf(sign) {return sign|9218868437227405312;}
// Nonnegative word shifted right, with every discarded bit jammed into bit0.
fn f64_shr_jam(a,n) {
	if n<=0 {return a;}
	if n>=63 {return a!=0;}
	let q=a>>n;
	if (a&((1<<n)-1))!=0 {q=q|1;}
	return q;
}
fn f64_pack(sign,exponent,sig) {
	if sig==0 {return sign;}
	if sig>=72057594037927936 {
		let i=0;
		while i<64 {
			if sig>=72057594037927936 {sig=f64_shr_jam(sig,1);exponent=exponent+1;}
			i=i+1;
		}
	}
	if sig<36028797018963968 && exponent>1 {
		let i=0;
		while i<64 {
			if sig<36028797018963968 && exponent>1 {sig=sig<<1;exponent=exponent-1;}
			i=i+1;
		}
	}
	if exponent<=0 {sig=f64_shr_jam(sig,1-exponent);exponent=1;}
	let mant=sig>>3;let remainder=sig&7;
	if remainder>4 || (remainder==4 && (mant&1)!=0) {mant=mant+1;}
	if mant>=9007199254740992 {mant=mant>>1;exponent=exponent+1;}
	if exponent>=2047 {return f64_inf(sign);}
	if mant<4503599627370496 {exponent=0;}
	return sign|(exponent<<52)|(mant&4503599627370495);
}
fn f64_add(a,b) {
	if f64_is_nan(a) || f64_is_nan(b) {return f64_nan();}
	let sa=f64_sign(a);let sb=f64_sign(b);let ea=f64_exponent(a);let eb=f64_exponent(b);
	if ea==2047 {if eb==2047 && sa!=sb {return f64_nan();}return f64_inf(sa);}
	if eb==2047 {return f64_inf(sb);}
	let ma=f64_fraction(a);let mb=f64_fraction(b);
	if ea!=0 {ma=ma|4503599627370496;}else {ea=1;}
	if eb!=0 {mb=mb|4503599627370496;}else {eb=1;}
	if ea<eb || (ea==eb && ma<mb) {let t=ea;ea=eb;eb=t;t=ma;ma=mb;mb=t;t=sa;sa=sb;sb=t;}
	ma=ma<<3;mb=f64_shr_jam(mb<<3,ea-eb);
	if sa==sb {return f64_pack(sa,ea,ma+mb);}
	if ma==mb {return 0;}
	return f64_pack(sa,ea,ma-mb);
}
fn f64_sub(a,b) {return f64_add(a,b^(-9223372036854775807-1));}
fn f64_normal_shift(mant) {
	if mant<=0 || mant>=4503599627370496 {return 0;}
	let n=0;let i=0;
	while i<64 {
		if mant>0 && mant<4503599627370496 {mant=mant<<1;n=n+1;}
		i=i+1;
	}
	return n;
}
fn f64_mul(a,b) {
	if f64_is_nan(a) || f64_is_nan(b) {return f64_nan();}
	let sign=f64_sign(a)^f64_sign(b);let aa=f64_magnitude(a);let bb=f64_magnitude(b);
	if f64_exponent(a)==2047 || f64_exponent(b)==2047 {if aa==0 || bb==0 {return f64_nan();}return f64_inf(sign);}
	if aa==0 || bb==0 {return sign;}
	let ea=f64_exponent(a);let eb=f64_exponent(b);let ma=f64_fraction(a);let mb=f64_fraction(b);
	if ea!=0 {ma=ma|4503599627370496;}else {ea=1;}
	if eb!=0 {mb=mb|4503599627370496;}else {eb=1;}
	let shift=f64_normal_shift(ma);ma=ma<<shift;ea=ea-shift;
	shift=f64_normal_shift(mb);mb=mb<<shift;eb=eb-shift;
	// 53 x 53 bits -> high54 / low52 bits, using base2^26 limbs.
	let a0=ma&67108863;let a1=ma>>26;let b0=mb&67108863;let b1=mb>>26;
	let p0=a0*b0;let p1=a0*b1+a1*b0;let p2=a1*b1;
	let middle=(p0>>26)+(p1&67108863);
	let low=(p0&67108863)|((middle&67108863)<<26);
	let high=p2+(p1>>26)+(middle>>26);
	let sig=(high<<3)|(low>>49);if (low&562949953421311)!=0 {sig=sig|1;}
	return f64_pack(sign,ea+eb-1023,sig);
}
fn f64_div(a,b) {
	if f64_is_nan(a) || f64_is_nan(b) {return f64_nan();}
	let sign=f64_sign(a)^f64_sign(b);let aa=f64_magnitude(a);let bb=f64_magnitude(b);
	let ea=f64_exponent(a);let eb=f64_exponent(b);
	if ea==2047 {if eb==2047 {return f64_nan();}return f64_inf(sign);}
	if eb==2047 {return sign;}
	if bb==0 {if aa==0 {return f64_nan();}return f64_inf(sign);}
	if aa==0 {return sign;}
	let ma=f64_fraction(a);let mb=f64_fraction(b);
	if ea!=0 {ma=ma|4503599627370496;}else {ea=1;}
	if eb!=0 {mb=mb|4503599627370496;}else {eb=1;}
	let shift=f64_normal_shift(ma);ma=ma<<shift;ea=ea-shift;
	shift=f64_normal_shift(mb);mb=mb<<shift;eb=eb-shift;
	let exponent=ea-eb+1023;if ma<mb {ma=ma<<1;exponent=exponent-1;}
	let quotient=ma/mb;let remainder=ma%mb;let i=0;
	while i<55 {
		quotient=quotient<<1;remainder=remainder<<1;
		if remainder>=mb {remainder=remainder-mb;quotient=quotient+1;}
		i=i+1;
	}
	if remainder!=0 {quotient=quotient|1;}
	return f64_pack(sign,exponent,quotient);
}
fn f64_eq(a,b) {
	if f64_is_nan(a) || f64_is_nan(b) {return 0;}
	return a==b || (f64_magnitude(a)==0 && f64_magnitude(b)==0);
}
fn f64_lt(a,b) {
	if f64_is_nan(a) || f64_is_nan(b) {return 0;}
	let aa=f64_magnitude(a);let bb=f64_magnitude(b);if aa==0 && bb==0 {return 0;}
	let sa=f64_sign(a);let sb=f64_sign(b);if sa!=sb {return sa!=0;}
	if sa!=0 {return aa>bb;}return aa<bb;
}
fn f64_le(a,b) {return f64_lt(a,b) || f64_eq(a,b);}
fn f64_gt(a,b) {return f64_lt(b,a);}
fn f64_ge(a,b) {return f64_le(b,a);}
fn f64_ne(a,b) {return f64_eq(a,b)==0;}
fn f64_from_i64(value) {
	let sign=0;if value<0 {sign=(-9223372036854775807-1);}
	if value==(-9223372036854775807-1) {return sign|(1086<<52);}
	let mag=value;if mag<0 {mag=-mag;}
	return f64_pack(sign,1078,mag);
}
// mode0 truncation, mode1 nearest ties-even, mode2 nearest ties-away.
fn f64_to_i64_mode(a,mode) {
	if f64_is_nan(a) {return 0;}
	let sign=f64_sign(a);let exponent=f64_exponent(a)-1023;
	if exponent>=63 {if sign!=0 {return (-9223372036854775807-1);}return 9223372036854775807;}
	let mant=f64_fraction(a)|4503599627370496;let mag=0;
	if exponent<0 {
		if mode!=0 && exponent==(-1) && (f64_fraction(a)!=0 || mode==2) {mag=1;}
	}else if exponent>=52 {mag=mant<<(exponent-52);}
	else {
		let shift=52-exponent;mag=mant>>shift;let rem=mant&((1<<shift)-1);let half=1<<(shift-1);
		if mode!=0 && (rem>half || (rem==half && ((mag&1)!=0 || mode==2))) {mag=mag+1;}
	}
	if sign!=0 {return -mag;}return mag;
}
fn f64_to_i64_trunc(a) {return f64_to_i64_mode(a,0);}
fn f64_to_i64_nearest(a) {return f64_to_i64_mode(a,1);}
fn f64_to_i64_round(a) {return f64_to_i64_mode(a,2);}
// Restoring square root: the 112-bit radicand is mantissa followed by58
// zero bits, consumed two bits at a time. Remainder/root fit signed i64.
fn f64_sqrt(a) {
	if f64_is_nan(a) {return f64_nan();}
	let mag=f64_magnitude(a);if mag==0 {return a;}
	if f64_sign(a)!=0 {return f64_nan();}
	if f64_exponent(a)==2047 {return a;}
	let exponent=f64_exponent(a);let mant=f64_fraction(a);
	if exponent!=0 {mant=mant|4503599627370496;}else {exponent=1;}
	let shift=f64_normal_shift(mant);mant=mant<<shift;exponent=exponent-shift-1023;
	if exponent%2!=0 {mant=mant<<1;exponent=exponent-1;}
	let root=0;let remainder=0;let i=0;
	while i<56 {
		let bit=110-i*2;let pair=0;if bit>=58 {pair=(mant>>(bit-58))&3;}
		remainder=(remainder<<2)|pair;let trial=(root<<2)|1;
		root=root<<1;if remainder>=trial {remainder=remainder-trial;root=root|1;}
		i=i+1;
	}
	if remainder!=0 {root=root|1;}
	return f64_pack(0,exponent/2+1023,root);
}
