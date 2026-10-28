// Independent pixel scatter and command symmetry checks for sequence mirrors.
import "../control/training.flex";
import "../control/augmentation.flex";
fn am_feedback() {
    let proprio=alloc(28);let target=alloc(16);let original=alloc(44);let i=0;
    while i<7 {pb_put32(proprio+i*4,pb_f64_to_f32(vc_number(i-3,5)));i=i+1;}
    pb_put32(target,0x3f19999a);pb_put32(target+4,0x3f800000);pb_put32(target+8,0x3f800000);pb_put32(target+12,0x3f800000);
    vc_copy(original,proprio,28);vc_copy(original+28,target,16);pm_feedback(proprio,target,0x3f800000);
    vc_require(pb_u32(proprio)==(pb_u32(original)^0x80000000) && pb_u32(proprio+4)==pb_u32(original+4),"mirror changed the wrong previous control axis");
    vc_require(pb_u32(proprio+8)==pb_u32(original+12) && pb_u32(proprio+12)==pb_u32(original+8) && pb_u32(proprio+16)==(pb_u32(original+16)^0x80000000),"mirror did not swap wheel feedback and reverse steering servo");
    vc_require(pb_u32(proprio+20)==pb_u32(original+20) && pb_u32(proprio+24)==pb_u32(original+24),"mirror changed contact or reserved event feedback");
    vc_require(pb_u32(target)==0xbf19999a && pb_u32(target+4)==0x3f800000 && pb_u32(target+8)==0x3f800000 && pb_u32(target+12)==0x3f800000,"mirror changed speed, phase or supervision");
    pm_feedback(proprio,target,0x3f800000);i=0;while i<28 {vc_require(load8(proprio+i)==load8(original+i),"feedback reflection is not an exact involution");i=i+1;}i=0;while i<16 {vc_require(load8(target+i)==load8(original+28+i),"target reflection is not an exact involution");i=i+1;}
    pb_zero(proprio,28);pb_zero(target,16);pm_feedback(proprio,target,0);i=0;while i<28 {vc_require(!load8(proprio+i),"mirror changed padding feedback");i=i+1;}i=0;while i<16 {vc_require(!load8(target+i),"mirror changed padding targets");i=i+1;}
    let pose=alloc(20);let pose_original=alloc(20);pb_put32(pose,0x3e800000);pb_put32(pose+4,0x3e000000);pb_put32(pose+8,0x3f000000);pb_put32(pose+12,0x3f5db3d7);pb_put32(pose+16,0x3f800000);vc_copy(pose_original,pose,20);pm_pose(pose,0x3f800000);
    vc_require(pb_u32(pose)==pb_u32(pose_original) && pb_u32(pose+4)==(pb_u32(pose_original+4)^0x80000000) && pb_u32(pose+8)==(pb_u32(pose_original+8)^0x80000000) && pb_u32(pose+12)==pb_u32(pose_original+12) && pb_u32(pose+16)==pb_u32(pose_original+16),"mirror changed the wrong relative-pose components");pm_pose(pose,0x3f800000);i=0;while i<20 {vc_require(load8(pose+i)==load8(pose_original+i),"pose reflection is not an exact involution");i=i+1;}pb_zero(pose,20);pm_pose(pose,0);i=0;while i<20 {vc_require(!load8(pose+i),"mirror changed pose padding");i=i+1;}
    pm_rng=109;let expected=pm_mask(2,1);let after=pm_rng;pm_rng=109;vc_require(expected==pm_mask(8,1) && after==pm_rng && !(expected&254),"inactive batch items consume mirror randomness");
    return 0;
}
fn am_pixels(side) {
    let batch=2;let length=3;let plane=side*side;let frame_bytes=3*plane;let count=batch*length*frame_bytes;let source=alloc(count);let expected=alloc(count*4);let actual=alloc(count*4);let input=vp_buffer(count);let output=vp_buffer(count*4);let i=0;
    while i<count {store8(source+i,(i*17+i/side+i/plane*13)%251);i=i+1;}pt_upload(input,source,count);let mask=0;
    while mask<4 {
        // Scatter the independent CPU reference by (time,item,channel,y,x).
        let t=0;while t<length {let b=0;while b<batch {let c=0;while c<3 {let y=0;while y<side {let x=0;while x<side {
            let destination_x=x;if (mask>>b)&1 {destination_x=side-1-x;}let frame=t*batch+b;let from=frame*frame_bytes+c*plane+y*side+x;let to=frame*frame_bytes+c*plane+y*side+destination_x;
            pb_put32(expected+to*4,pb_f64_to_f32(vc_number(load8(source+from),255)));x=x+1;}y=y+1;}c=c+1;}b=b+1;}t=t+1;}
        let mode=104;if side==128 {mode=105;}pt_dispatch(pt_launch(input,output,count,mode,batch,mask,0));vp_check(device_stream_wait(vp_stream));vp_check(device_download(actual,output,count*4));i=0;
        while i<count {vc_require(pb_u32(actual+i*4)==pb_u32(expected+i*4),"GPU sequence mirror differs from independent pixel scatter");i=i+1;}
        if !mask {pt_dispatch(pt_launch(input,output,count,103,0,0,0));vp_check(device_stream_wait(vp_stream));vp_check(device_download(actual,output,count*4));i=0;while i<count {vc_require(pb_u32(actual+i*4)==pb_u32(expected+i*4),"disabled mirror changes native normalization");i=i+1;}}
        mask=mask+1;
    }return 0;
}
fn am_fixture(output,mirror) {
    let length=5;let stride=length*21224;let bytes=32+2*stride;let data=alloc(bytes);vc_copy(data,"PVDATA03",8);store64(data+8,2);store64(data+16,1);store64(data+24,length);let episode=0;
    while episode<2 {let base=data+32+episode*stride;let t=0;while t<4 {let c=0;while c<3 {let y=0;while y<84 {let x=0;while x<84 {let destination=x;if mirror && !episode {destination=83-x;}store8(base+t*21168+c*7056+y*84+destination,(x*13+y*7+c*31+t*11+episode*23)%251);x=x+1;}y=y+1;}c=c+1;}
            let row=base+length*21168+t*56;pb_put32(row,pb_f64_to_f32(vc_number(t,10)));pb_put32(row+4,0x3f800000);pb_put32(row+8,0x3e4ccccd);pb_put32(row+12,0x3f4ccccd);pb_put32(row+16,0x3dcccccd);
            let steering=0xbf19999a;if t==1 || t==3 {steering=0;}if t==2 {steering=0x3f19999a;}pb_put32(row+28,steering);if t<3 {pb_put32(row+32,0x3f800000);}if t>=2 {pb_put32(row+36,0x3f800000);}if t {pb_put32(row+40,0x3f800000);}pb_put32(row+44,0x3f800000);vc_copy(row+48,row+28,8);
            if mirror && !episode {pm_feedback(row,row+28,0x3f800000);pb_put32(row+48,pb_u32(row+48)^0x80000000);}t=t+1;
        }episode=episode+1;
    }let name="original.bin";if mirror {name="mirrored-fit.bin";}vc_write(vc_path(output,name),data,bytes);return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"visual-control-augmentation KERNELS OUTPUT");let output=vc_absolute(load64(argv+16));vc_mkdir(output);am_feedback();am_fixture(output,0);am_fixture(output,1);vp_init(load64(argv+8),2,0);
    let image=vp_map(vc_path(load64(argv+8),"gradients.ptx"));let module=device_module(image);vc_require(module,device_error());pt_function=device_function(module,"flex_kernel");vc_require(pt_function,device_error());am_pixels(84);am_pixels(128);
    vc_save_text(vc_path(output,"result.json"),"{\"passed\":true,\"runtime\":\"Flexscript/Pup CUDA\",\"pythonRequired\":false,\"independentPixelScatterChecked\":true,\"completeHistoriesMirroredConsistently\":true,\"feedbackAndTargetInvolutionChecked\":true,\"paddingUnchanged\":true,\"inactiveBatchRandomnessExcluded\":true,\"disabledNormalizationBitIdentical\":true}\n");pl_print(1,"Native recurrent sequence mirror contracts passed.\n");return 0;
}
