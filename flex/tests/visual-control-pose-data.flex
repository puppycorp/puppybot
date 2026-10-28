// Synthetic sequence fixtures for pose-target gradients, masking and mirrors.
import "../control/dataset.flex";
import "../control/augmentation.flex";
fn pd_data(path,mirror) {
    let length=4;let stride=length*21224;let bytes=32+2*stride;let data=alloc(bytes);vc_copy(data,"PVDATA03",8);store64(data+8,2);store64(data+16,1);store64(data+24,length);let episode=0;
    while episode<2 {let base=data+32+episode*stride;let t=0;while t<3 {let c=0;while c<3 {let y=0;while y<84 {let x=0;while x<84 {let destination=x;if mirror && !episode {destination=83-x;}store8(base+t*21168+c*7056+y*84+destination,(x*13+y*7+c*31+t*11+episode*23)%251);x=x+1;}y=y+1;}c=c+1;}
            let row=base+length*21168+t*56;if t {pb_put32(row,0x3f19999a);pb_put32(row+4,0x3f800000);pb_put32(row+8,0x3e4ccccd);pb_put32(row+12,0x3f4ccccd);pb_put32(row+16,0x3dcccccd);}pb_put32(row+28,0x3f19999a);pb_put32(row+32,0x3f800000);if t==2 {pb_put32(row+36,0x3f800000);}pb_put32(row+40,0x3f800000);pb_put32(row+44,0x3f800000);vc_copy(row+48,row+28,8);if mirror && !episode {pm_feedback(row,row+28,0x3f800000);pb_put32(row+48,pb_u32(row+48)^0x80000000);}t=t+1;
        }episode=episode+1;}
    vc_write(path,data,bytes);return vc_digest(data,bytes);
}
fn pd_targets(directory,data_sha,variant,mirror) {
    vc_mkdir(directory);let bytes=32+2*4*20;let data=alloc(bytes);vc_copy(data,"PVPOSE01",8);store64(data+8,2);store64(data+16,1);store64(data+24,4);let episode=0;
    while episode<2 {let t=0;while t<3 {let row=data+32+(episode*4+t)*20;let x=vc_number(t,10);let y=vc_number(t,20);if (variant==1 && !episode) || (variant==2 && episode) {x=pb_neg(x);y=pb_neg(y);}pb_put32(row,pb_f64_to_f32(x));pb_put32(row+4,pb_f64_to_f32(y));pb_put32(row+12,0x3f800000);pb_put32(row+16,0x3f800000);if mirror && !episode {pb_put32(row+4,pb_u32(row+4)^0x80000000);pb_put32(row+8,pb_u32(row+8)^0x80000000);}t=t+1;}episode=episode+1;}
    if variant==3 {pb_put32(data+32+2*20+16,0);}if variant==6 {pb_put32(data+32+20+8,0x3f800000);}if variant==7 {pb_put32(data+32+3*20,0x3f800000);}
    let sha=vc_digest(data,bytes);if variant==4 {pb_put32(data+32+20,pb_u32(data+32+20)^1);}vc_write(vc_path(directory,"targets.bin"),data,bytes);
    if variant==5 {data_sha="wrong";}let text=alloc(2048);let b=alloc(32);pl_builder(b,text,2048);pl_text(b,"{\"passed\":true,\"verifiedAgainstPhysicalTrace\":true,\"actorInputsUnchanged\":true,\"syntheticUnitFixture\":true,\"normalizationMetres\":8,\"episodes\":2,\"fittingHistories\":1,\"validationHistories\":1,\"sequenceLength\":4,\"sourceDataSHA256\":");pj_text(b,data_sha);pl_text(b,",\"targetsSHA256\":");pj_text(b,sha);pl_text(b,"}\n");vc_require(!load64(b+24),"synthetic pose receipt overflow");vc_write(vc_path(directory,"receipt.json"),text,load64(b+8));return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2,"pose-fixtures NEW_OUTPUT");let output=vc_absolute(load64(argv+8));vc_mkdir(output);let source_sha=pd_data(vc_path(output,"data.bin"),0);let mirrored_sha=pd_data(vc_path(output,"mirrored-data.bin"),1);let variant=0;while variant<8 {pd_targets(vc_path(output,vc_concat("pose-",vc_int(variant))),source_sha,variant,0);variant=variant+1;}pd_targets(vc_path(output,"pose-mirrored"),mirrored_sha,0,1);return 0;
}
