import "backend.flex";
global vi_width=0;
global vi_height=0;
global vi_scale=0;
global vi_left=0;
global vi_top=0;
fn vi_dimensions(w,h) {vp_require(w>=1 && h>=1 && w<=8192 && h<=8192 && w*h<=16777216,"image exceeds 8192 pixels/axis or 16 Mi pixels");vi_width=w;vi_height=h;return 0;}
fn vi_decode(data,size) {
    vp_require(size>8,"image data is too short");
    if pb_u32(data)==0x474e5089 {
        let library=ffi_open("libpng16.so.16");vp_require(library,"libpng16.so.16 unavailable");let begin=ffi_symbol(library,"png_image_begin_read_from_memory");let finish=ffi_symbol(library,"png_image_finish_read");let release=ffi_symbol(library,"png_image_free");vp_require(begin && finish && release,"PNG decoder symbols unavailable");
        let image=alloc(104);pb_put32(image+8,1);vp_require(ffi_call_i32(begin,image,data,size,0,0,0),"invalid PNG header");vi_dimensions(pb_u32(image+12),pb_u32(image+16));pb_put32(image+20,2);let rgb=alloc(vi_width*vi_height*3);let ok=ffi_call_i32(finish,image,0,rgb,0,0,0);ffi_call(release,image,0,0,0,0,0);vp_require(ok,"PNG decompression failed");syscall(11,image,104,0,0,0,0);return rgb;
    }
    vp_require(load8(data)==255 && load8(data+1)==216,"expected a PNG or JPEG image");
    let library=ffi_open("libturbojpeg.so.0");vp_require(library,"libturbojpeg.so.0 unavailable");let init=ffi_symbol(library,"tjInitDecompress");let header=ffi_symbol(library,"tjDecompressHeader2");let decode=ffi_symbol(library,"tjDecompress2");let release=ffi_symbol(library,"tjDestroy");vp_require(init && header && decode && release,"JPEG decoder symbols unavailable");
    let handle=ffi_call(init,0,0,0,0,0,0);vp_require(handle,"JPEG decoder initialization failed");let dims=alloc(24);vp_require(!ffi_call_i32(header,handle,data,size,dims,dims+8,dims+16),"invalid JPEG header");vi_dimensions(pb_u32(dims),pb_u32(dims+8));let rgb=alloc(vi_width*vi_height*3);let args=alloc(88);store64(args,handle);store64(args+8,data);store64(args+16,size);store64(args+24,rgb);store64(args+32,vi_width);store64(args+40,vi_width*3);store64(args+48,vi_height);store64(args+56,0);store64(args+64,0);let ok=ffi_call_words(decode,args);ffi_call(release,handle,0,0,0,0,0);vp_require(!ok,"JPEG decompression failed");syscall(11,args,88,0,0,0,0);syscall(11,dims,24,0,0,0,0);return rgb;
}
fn vi_image(path) {let data=alloc(16777217);let size=pl_read_file(path,data,16777216);vp_require(size>8,"cannot read image (maximum encoded size 16 MiB)");let rgb=vi_decode(data,size);syscall(11,data,16777217,0,0,0,0);return rgb;}
// RGB -> NCHW with half-pixel bilinear sampling and 114 grey letterboxing.
// Precomputed 16-bit interpolation weights keep camera preprocessing bounded.
fn vi_axis(length,resized) {
    let map=alloc(resized*24);let i=0;
    while i<resized {let fixed=((2*i+1)*length*32768)/resized-32768;let first=fixed/65536;if fixed<0 {first=-1;}let fraction=fixed-first*65536;store64(map+i*24,pb_clamp(first,0,length-1));store64(map+i*24+8,pb_clamp(first+1,0,length-1));store64(map+i*24+16,fraction);i=i+1;}return map;
}
fn vi_preprocess(rgb,width,height) {
    vp_require(vp_rank(vp_input)==4 && vp_dim(vp_input,0)==1 && vp_dim(vp_input,1)==3,"detector image input must be batch-one RGB NCHW");let iw=vp_dim(vp_input,3);let ih=vp_dim(vp_input,2);
    let scale=pb_fmin(f64_div(f64_from_i64(iw),f64_from_i64(width)),f64_div(f64_from_i64(ih),f64_from_i64(height)));vi_scale=scale;
    let rw=pb_max(1,f64_to_i64_nearest(f64_mul(f64_from_i64(width),scale)));let rh=pb_max(1,f64_to_i64_nearest(f64_mul(f64_from_i64(height),scale)));vi_left=(iw-rw)/2;vi_top=(ih-rh)/2;let output=alloc(iw*ih*12);let table=alloc(1024);let i=0;while i<256 {pb_put32(table+i*4,pb_f64_to_f32(f64_div(f64_from_i64(i),f64_from_i64(255))));i=i+1;}
    let xs=vi_axis(width,rw);let ys=vi_axis(height,rh);let y=0;
    while y<ih {let x=0;while x<iw {let c=0;while c<3 {let value=114;
        if x>=vi_left && x<vi_left+rw && y>=vi_top && y<vi_top+rh {
            let xm=xs+(x-vi_left)*24;let ym=ys+(y-vi_top)*24;let fx=load64(xm+16);let fy=load64(ym+16);let a=load8(rgb+(load64(ym)*width+load64(xm))*3+c);let b=load8(rgb+(load64(ym)*width+load64(xm+8))*3+c);let d=load8(rgb+(load64(ym+8)*width+load64(xm))*3+c);let e=load8(rgb+(load64(ym+8)*width+load64(xm+8))*3+c);
            let sum=(a*(65536-fx)+b*fx)*(65536-fy)+(d*(65536-fx)+e*fx)*fy;value=sum>>32;let remainder=sum&0xffffffff;if remainder>0x80000000 || (remainder==0x80000000 && (value&1)) {value=value+1;}
        }
        pb_put32(output+((c*ih+y)*iw+x)*4,pb_u32(table+value*4));c=c+1;
    }x=x+1;}y=y+1;}
    syscall(11,xs,rw*24,0,0,0,0);syscall(11,ys,rh*24,0,0,0,0);syscall(11,table,1024,0,0,0,0);return output;
}
