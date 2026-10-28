// Zero only the recurrent input rows for previous drive commands and speeds.
import "host.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==4,"ablate-drive-feedback INPUT_WEIGHTS NEW_WEIGHTS NEW_REPORT");
    let input=vc_absolute(load64(argv+8));let output=vc_absolute(load64(argv+16));let report=vc_absolute(load64(argv+24));
    vc_require(!pl_equal(input,output) && !pl_equal(input,report) && !pl_equal(output,report) && syscall(21,output,0,0,0,0,0) && syscall(21,report,0,0,0,0,0),"ablation outputs must be new files");
    let original=vc_map(input);let size=vc_size;vc_require(size>=32 && load64(original)==0x3130303056505550,"invalid Pup checkpoint");
    let tensors=load64(original+8);let base=load64(original+16);vc_require(tensors>=1 && tensors<=4096 && base==32+tensors*256 && base<=size && load64(original+24)==size-base,"invalid checkpoint directory");
    let found=0;let i=0;while i<tensors {let row=original+32+i*256;vc_require(!load8(row+191),"unterminated tensor name");if pl_equal(row,"memory.weight_ih_T") {vc_require(!found,"duplicate recurrent input tensor");found=row;}i=i+1;}
    vc_require(found && load64(found+192)==2 && load64(found+200)==263*768 && load64(found+216)==263 && load64(found+224)==768,"expected 256-memory recurrent input tensor");
    let offset=load64(found+208);let bytes=263*768*4;vc_require(offset>=0 && offset<=size-base && bytes<=size-base-offset,"recurrent tensor exceeds checkpoint");
    let first=base+offset+256*768*4;let removed=5*768*4;vc_require(first>=base && first+removed<=size,"drive feedback rows exceed checkpoint");
    let copy=alloc(size);vc_require(copy>0,"cannot allocate ablated checkpoint");vc_copy(copy,original,size);let changed=0;i=0;while i<removed {if load8(copy+first+i) {changed=changed+1;}store8(copy+first+i,0);i=i+1;}
    vc_require(changed>0,"drive feedback rows are already zero");vc_write(output,copy,size);
    let text=alloc(2048);let b=alloc(32);pl_builder(b,text,2048);pl_text(b,"{\"passed\":true,\"sourceSHA256\":");pj_text(b,vc_digest(original,size));pl_text(b,",\"weightsSHA256\":");pj_text(b,vc_digest(copy,size));
    pl_text(b,",\"tensor\":\"memory.weight_ih_T\",\"firstByte\":");pl_int(b,first);pl_text(b,",\"bytesZeroed\":");pl_int(b,removed);pl_text(b,",\"nonzeroBytesChanged\":");pl_int(b,changed);
    pl_text(b,",\"driveFeedbackValuesZeroed\":5,\"contactFeedbackPreserved\":true,\"otherWeightsPreserved\":true,\"trainingPerformed\":false,\"automaticPromotion\":false}\n");vc_require(!load64(b+24),"ablation report overflow");vc_write(report,text,load64(b+8));
    syscall(11,original,size,0,0,0,0);pl_write(1,text,load64(b+8));return 0;
}
