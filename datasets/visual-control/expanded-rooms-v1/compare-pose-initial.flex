// Verify that adding a training-only pose head preserves every existing tensor.
import "../../../flex/control/host.flex";
fn cm_find(data,bytes,name,required) {
    vc_require(bytes>=32 && load64(data)==load64("PUPV0001") && load64(data+8)>0 && load64(data+8)<=4096 && load64(data+16)==32+load64(data+8)*256 && load64(data+16)<=bytes && load64(data+24)==bytes-load64(data+16),"invalid checkpoint");
    let found=0;let i=0;while i<load64(data+8) {let row=data+32+i*256;vc_require(!load8(row+191),"unterminated checkpoint parameter name");if pl_equal(row,name) {vc_require(!found,"duplicate checkpoint parameter");found=row;}i=i+1;}
    if required {vc_require(found,"missing original checkpoint parameter");}
    if found {let count=load64(found+200);let offset=load64(found+208);vc_require(load64(found+192)>=1 && load64(found+192)<=4 && count>0 && offset>=0 && offset<=bytes-load64(data+16) && count<=(bytes-load64(data+16)-offset)/4,"invalid checkpoint parameter dimensions");}return found;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==4,"compare-pose-initial BASELINE CANDIDATE OUTPUT_JSON");let old=vc_map(vc_absolute(load64(argv+8)));let old_bytes=vc_size;let next=vc_map(vc_absolute(load64(argv+16)));let next_bytes=vc_size;
    let head=cm_find(next,next_bytes,"critic.pose.weight_T",1);let bias=cm_find(next,next_bytes,"critic.pose.bias",1);let width=load64(head+216);vc_require((width==128 || width==256) && load64(head+192)==2 && load64(head+224)==4 && load64(head+200)==width*4 && load64(bias+192)==1 && load64(bias+216)==4 && load64(bias+200)==4,"invalid pose readout dimensions");
    vc_require(!cm_find(old,old_bytes,"critic.pose.weight_T",0) && !cm_find(old,old_bytes,"critic.pose.bias",0),"baseline already contains pose readout");
    let compare=ffi_symbol(ffi_open("libc.so.6"),"memcmp");vc_require(compare,"memcmp unavailable");let count=0;let i=0;
    while i<load64(old+8) {let a=cm_find(old,old_bytes,old+32+i*256,1);let b=cm_find(next,next_bytes,a,1);vc_require(load64(a+192)==load64(b+192) && load64(a+200)==load64(b+200),"original parameter shape changed");let axis=0;while axis<4 {vc_require(load64(a+216+axis*8)==load64(b+216+axis*8),"original parameter dimension changed");axis=axis+1;}
        let n=load64(a+200)*4;vc_require(!ffi_call(compare,old+load64(old+16)+load64(a+208),next+load64(next+16)+load64(b+208),n,0,0,0),"original checkpoint tensor changed");count=count+load64(a+200);i=i+1;
    }
    let added=0;i=0;while i<load64(next+8) {let row=next+32+i*256;if !cm_find(old,old_bytes,row,0) {vc_require(pl_equal(row,"critic.pose.weight_T") || pl_equal(row,"critic.pose.bias"),"unexpected additional checkpoint parameter");added=added+1;}i=i+1;}
    vc_require(added==2,"pose checkpoint must add exactly two parameters");let text=alloc(1024);let b=alloc(32);pl_builder(b,text,1024);pl_text(b,"{\"passed\":true,\"allOriginalParametersByteIdentical\":true,\"addedPoseHeadOnly\":true,\"memoryWidth\":");pl_int(b,width);pl_text(b,",\"originalParameters\":");pl_int(b,count);pl_text(b,",\"addedPoseParameters\":");pl_int(b,width*4+4);pl_text(b,",\"baselineSHA256\":");pj_text(b,vc_digest(old,old_bytes));pl_text(b,",\"candidateSHA256\":");pj_text(b,vc_digest(next,next_bytes));pl_text(b,"}\n");vc_require(!load64(b+24),"comparison receipt exceeds capacity");vc_write(vc_absolute(load64(argv+24)),text,load64(b+8));return 0;
}
