// Verify that adding histories did not alter any existing target labels.
import "../../../flex/control/host.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==4,"target-preserve OLD_TARGETS EXPANDED_TARGETS OUTPUT");let old=vc_map(vc_absolute(load64(argv+8)));let old_bytes=vc_size;let next=vc_map(vc_absolute(load64(argv+16)));let next_bytes=vc_size;let length=load64(old+24);
    vc_require(load64(old)==load64("PVVIS001") && load64(old+8)==172 && load64(old+16)==136 && length==354 && old_bytes==32+172*length*12,"unexpected original target dimensions");
    vc_require(load64(next)==load64("PVVIS001") && load64(next+8)==202 && load64(next+16)==160 && load64(next+24)==length && next_bytes==32+202*length*12,"unexpected expanded target dimensions");
    let compare=ffi_symbol(ffi_open("libc.so.6"),"memcmp");vc_require(compare,"memcmp unavailable");let episode=0;while episode<172 {let target=episode;if episode>=136 {target=episode+24;}vc_require(!ffi_call(compare,old+32+episode*length*12,next+32+target*length*12,length*12,0,0,0),"existing target labels changed");episode=episode+1;}
    let text=alloc(1024);let b=alloc(32);pl_builder(b,text,1024);pl_text(b,"{\"passed\":true,\"existingHistoriesPreserved\":172,\"fittingHistories\":136,\"validationHistories\":36,\"sequenceLength\":354,\"oldTargetSHA256\":");pj_text(b,vc_digest(old,old_bytes));pl_text(b,",\"expandedTargetSHA256\":");pj_text(b,vc_digest(next,next_bytes));pl_text(b,"}\n");vc_require(!load64(b+24),"target preservation report overflow");vc_write(vc_absolute(load64(argv+24)),text,load64(b+8));return 0;
}
