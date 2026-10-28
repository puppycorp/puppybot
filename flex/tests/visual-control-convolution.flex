// Independent CPU scatter reference for every convolution-input gradient.
import "../control/training.flex";
import "../control/host.flex";
fn cv_case(index,output,batch,cin,cout,ih,iw,k,stride,pad) {
    let oh=(ih+2*pad-k)/stride+1;let ow=(iw+2*pad-k)/stride+1;let count=batch*cin*ih*iw;let weights=alloc(cout*cin*k*k*4);let upstream=alloc(batch*cout*oh*ow*4);let expected=alloc(count*8);let actual=alloc(count*4);let i=0;
    while i<cout*cin*k*k {pb_put32(weights+i*4,pb_f64_to_f32(vc_number((i*17+3)%103-51,97)));i=i+1;}i=0;while i<batch*cout*oh*ow {pb_put32(upstream+i*4,pb_f64_to_f32(vc_number((i*31+7)%109-54,101)));i=i+1;}
    let b=0;while b<batch {let co=0;while co<cout {let y=0;while y<oh {let x=0;while x<ow {let gradient=pb_read_float(upstream+((b*cout+co)*oh*ow+y*ow+x)*4);let ci=0;while ci<cin {let ky=0;while ky<k {let kx=0;while kx<k {let iy=y*stride+ky-pad;let ix=x*stride+kx-pad;
        if iy>=0 && iy<ih && ix>=0 && ix<iw {let target=((b*cin+ci)*ih*iw+iy*iw+ix)*8;store64(expected+target,f64_add(load64(expected+target),f64_mul(gradient,pb_read_float(weights+((co*cin+ci)*k*k+ky*k+kx)*4))));}kx=kx+1;}ky=ky+1;}ci=ci+1;}x=x+1;}y=y+1;}co=co+1;}b=b+1;}
    let meta=alloc(192);store64(meta,12);store64(meta+64,batch);store64(meta+72,cout);store64(meta+80,oh);store64(meta+88,ow);store64(meta+96,batch);store64(meta+104,cin);store64(meta+112,ih);store64(meta+120,iw);store64(meta+160,k);store64(meta+168,stride);store64(meta+176,pad);
    let dw=vp_buffer(cout*cin*k*k*4);let dg=vp_buffer(batch*cout*oh*ow*4);let dm=vp_buffer(192);let result=vp_buffer(count*4);pt_upload(dw,weights,cout*cin*k*k*4);pt_upload(dg,upstream,batch*cout*oh*ow*4);pt_upload(dm,meta,192);pt_upload(result,actual,count*4);pt_dispatch(pt_launch(dg,result,count,0,0,dw,dm));vp_check(device_stream_wait(vp_stream));vp_check(device_download(actual,result,count*4));
    let maximum=0;i=0;while i<count {let value=pb_read_float(actual+i*4);let error=f64_magnitude(f64_sub(value,load64(expected+i*8)));maximum=pb_fmax(maximum,error);vc_require(f64_is_finite(value) && f64_lt(error,f64_mul(vc_number(1,100000),pb_fmax(PB_ONE,f64_magnitude(load64(expected+i*8))))),"convolution input gradient differs from CPU scatter reference");i=i+1;}
    vc_write(vc_path(output,vc_concat("case-",vc_concat(vc_int(index),".bin"))),actual,count*4);return maximum;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"visual-control-convolution KERNELS OUTPUT");let output=vc_absolute(load64(argv+16));vc_mkdir(output);vp_init(load64(argv+8),2,0);let image=vp_map(vc_path(load64(argv+8),"gradients.ptx"));let module=device_module(image);vc_require(module,device_error());pt_function=device_function(module,"flex_kernel");vc_require(pt_function,device_error());
    let maximum=cv_case(0,output,2,3,4,84,84,8,4,0);maximum=pb_fmax(maximum,cv_case(1,output,2,2,5,11,12,4,2,1));maximum=pb_fmax(maximum,cv_case(2,output,2,3,4,9,10,5,3,2));maximum=pb_fmax(maximum,cv_case(3,output,1,2,3,7,8,3,1,1));maximum=pb_fmax(maximum,cv_case(4,output,2,3,2,4,5,1,2,0));maximum=pb_fmax(maximum,cv_case(5,output,1,3,4,128,128,12,6,0));
    let text=alloc(1024);let b=alloc(32);pl_builder(b,text,1024);pl_text(b,"{\"passed\":true,\"runtime\":\"Flexscript/Pup CUDA\",\"oracle\":\"independent CPU output-gradient scatter\",\"cases\":6,\"paddingStridesAndUncoveredInputsChecked\":true,\"maxAbsError\":");pl_float(b,maximum);pl_text(b,"}\n");vc_write(vc_path(output,"result.json"),text,load64(b+8));pl_write(1,text,load64(b+8));return 0;
}
