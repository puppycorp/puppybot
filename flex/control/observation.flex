// Actor boundary: image pixels, previous controls and own drive/contact only.
import "host.flex";
global vc_normalized=0;
fn vc_pixels_init() {
    vc_normalized=alloc(256*4);let i=0;while i<256 {pb_put32(vc_normalized+i*4,pb_f64_to_f32(vc_number(i,255)));i=i+1;}return 0;
}
fn vc_resize_to(rgb,out,size) {
    // Exact box-area integration in integer units. No image library, sampling
    // aliases or scene geometry. Nearest-even rounding produces uint8 NCHW.
    vc_require(size>=1 && size<=480,"invalid actor image size");let y=0;while y<size {let x=0;while x<size {
        let c=0;while c<3 {let sum=0;let iy=y*480/size;
            while iy*size<(y+1)*480 {let wy=pb_min((iy+1)*size,(y+1)*480)-pb_max(iy*size,y*480);let ix=x*640/size;
                while ix*size<(x+1)*640 {let wx=pb_min((ix+1)*size,(x+1)*640)-pb_max(ix*size,x*640);
                    sum=sum+load8(rgb+(iy*640+ix)*3+c)*wx*wy;ix=ix+1;}iy=iy+1;}
            let value=sum/307200;let remainder=sum%307200;if remainder>153600 || (remainder==153600 && (value&1)) {value=value+1;}
            store8(out+(c*size+y)*size+x,value);c=c+1;}x=x+1;}y=y+1;}return out;
}
fn vc_resize(rgb,out) {return vc_resize_to(rgb,out,84);}
fn vc_feedback(drive,previous,contact,out) {
    vc_copy(out,previous,8);pb_put32(out+8,pb_f64_to_f32(f64_div(pj_real(drive,"leftSpeed"),f64_from_i64(100))));
    pb_put32(out+12,pb_f64_to_f32(f64_div(pj_real(drive,"rightSpeed"),f64_from_i64(100))));
    pb_put32(out+16,pb_f64_to_f32(f64_div(f64_sub(pj_real(drive,"steeringAngleDeg"),f64_from_i64(90)),f64_from_i64(45))));
    vc_require(!pj_error,"invalid own-state feedback");pb_put32(out+20,pb_f64_to_f32(f64_from_i64(contact)));pb_put32(out+24,0);return out;
}
fn vc_policy_input_dimensions(image,feedback,hidden,out,blackout,image_bytes,memory_width) {
    let i=0;while i<image_bytes {let value=0;if !blackout {value=pb_u32(vc_normalized+load8(image+i)*4);}pb_put32(out+i*4,value);i=i+1;}
    vc_copy(out+image_bytes*4,feedback,7*4);vc_copy(out+(image_bytes+7)*4,hidden,memory_width*4);return out;
}
fn vc_policy_input_sized(image,feedback,hidden,out,blackout,image_bytes) {return vc_policy_input_dimensions(image,feedback,hidden,out,blackout,image_bytes,128);}
fn vc_policy_input(image,feedback,hidden,out,blackout) {return vc_policy_input_sized(image,feedback,hidden,out,blackout,21168);}
