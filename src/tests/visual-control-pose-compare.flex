// Compare a named gradient tensor rather than only the new auxiliary head.
import "../control/host.flex";
fn pc_record(data,bytes,name) {
    vc_require(bytes>=32 && load64(data)==load64("PUPV0001") && load64(data+16)==32+load64(data+8)*256 && load64(data+16)<=bytes,"invalid gradient checkpoint");let i=0;let found=0;while i<load64(data+8) {let row=data+32+i*256;if pl_equal(row,name) {vc_require(!found,"duplicate gradient tensor");found=row;}i=i+1;}vc_require(found && load64(found+200)<=bytes/4 && load64(found+208)<=bytes-load64(data+16) && load64(found+200)*4<=bytes-load64(data+16)-load64(found+208),"missing gradient tensor");return found;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==4,"pose-compare GRADIENT_A GRADIENT_B PARAMETER");let a=vc_map(load64(argv+8));let a_bytes=vc_size;let b=vc_map(load64(argv+16));let b_bytes=vc_size;let name=load64(argv+24);let x=pc_record(a,a_bytes,name);let y=pc_record(b,b_bytes,name);vc_require(load64(x+200)==load64(y+200) && load64(x+192)==load64(y+192),"gradient tensor dimensions differ");let count=load64(x+200)*4;let p=a+load64(a+16)+load64(x+208);let q=b+load64(b+16)+load64(y+208);let i=0;while i<count {if load8(p+i)!=load8(q+i) {return 0;}i=i+1;}vc_require(0,"changing fitting pose labels did not alter the GRU gradient");return 2;
}
