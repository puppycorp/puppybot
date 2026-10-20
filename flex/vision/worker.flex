import "detect.flex";
fn vv_worker(manifest,kernel,backend) {
    vd_setup(manifest,kernel,backend);vd_limit=pb_min(vd_limit,100);let receive=alloc(49168);let bytes=alloc(131072);let b=alloc(32);
    let ready="{\"ready\":true}";vp_require(syscall(44,3,ready,14,16384,0,0)==14,"cannot announce worker readiness");
    while 1 {
        pl_wait(3,1,pl_now()+60000);let n=syscall(45,3,receive,49168,32,0,0);if !n {return 0;}
        if n!=-11 && n!=-4 {
        vp_require(n>=24 && n<=49168,"invalid camera frame packet");let rgb=vi_decode(receive+16,n-16);let w=vi_width;let h=vi_height;pl_builder(b,bytes,131072);let ok=vd_detect_rgb(rgb,w,h,load64(receive),load64(receive+8),b);syscall(11,rgb,w*h*3,0,0,0,0);
        let size=load64(b+8);if !ok || size>30000 {let error="{\"error\":\"Detection response exceeds live limit\"}";pb_copy(bytes,error,pl_size(error)+1);size=pl_size(error);}
        let sent=syscall(44,3,bytes,size,16384,0,0);if sent==-11 {if pl_wait(3,4,pl_now()+5000) {sent=syscall(44,3,bytes,size,16384,0,0);}}if sent!=size {return 1;}
        }
    }return 0;
}
