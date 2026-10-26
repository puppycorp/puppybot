// Actor boundary: image pixels, previous controls and own drive/contact only.
import "host.flex";
global vc_normalized=0;
fn vc_pixels_init() {
    vc_normalized=alloc(256*4);let i=0;while i<256 {pb_put32(vc_normalized+i*4,pb_f64_to_f32(vc_number(i,255)));i=i+1;}return 0;
}
fn vc_resize(rgb,out) {
    // Exact box-area integration in integer units. No image library, sampling
    // aliases or scene geometry. Nearest-even rounding produces uint8 NCHW.
    let y=0;while y<84 {let x=0;while x<84 {
        let c=0;while c<3 {let sum=0;let iy=y*480/84;
            while iy*84<(y+1)*480 {let wy=pb_min((iy+1)*84,(y+1)*480)-pb_max(iy*84,y*480);let ix=x*640/84;
                while ix*84<(x+1)*640 {let wx=pb_min((ix+1)*84,(x+1)*640)-pb_max(ix*84,x*640);
                    sum=sum+load8(rgb+(iy*640+ix)*3+c)*wx*wy;ix=ix+1;}iy=iy+1;}
            let value=sum/307200;let remainder=sum%307200;if remainder>153600 || (remainder==153600 && (value&1)) {value=value+1;}
            store8(out+(c*84+y)*84+x,value);c=c+1;}x=x+1;}y=y+1;}return out;
}
fn vc_feedback(drive,previous,contact,out) {
    vc_copy(out,previous,8);pb_put32(out+8,pb_f64_to_f32(f64_div(pj_real(drive,"leftSpeed"),f64_from_i64(100))));
    pb_put32(out+12,pb_f64_to_f32(f64_div(pj_real(drive,"rightSpeed"),f64_from_i64(100))));
    pb_put32(out+16,pb_f64_to_f32(f64_div(f64_sub(pj_real(drive,"steeringAngleDeg"),f64_from_i64(90)),f64_from_i64(45))));
    vc_require(!pj_error,"invalid own-state feedback");pb_put32(out+20,pb_f64_to_f32(f64_from_i64(contact)));pb_put32(out+24,0);return out;
}
fn vc_policy_input(image,feedback,hidden,out,blackout) {
    let i=0;while i<21168 {let value=0;if !blackout {value=pb_u32(vc_normalized+load8(image+i)*4);}pb_put32(out+i*4,value);i=i+1;}
    vc_copy(out+21168*4,feedback,7*4);vc_copy(out+(21168+7)*4,hidden,128*4);return out;
}
