// Verify the recurrent rows for drive feedback remain zero after training.
import "host.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"verify-drive-feedback-zero WEIGHTS NEW_REPORT");let path=vc_absolute(load64(argv+8));let report=vc_absolute(load64(argv+16));
    vc_require(!pl_equal(path,report) && syscall(21,report,0,0,0,0,0),"verification report must be new");let data=vc_map(path);let size=vc_size;
    vc_require(size>=32 && load64(data)==0x3130303056505550,"invalid Pup checkpoint");let tensors=load64(data+8);let base=load64(data+16);
    vc_require(tensors>=1 && tensors<=4096 && base==32+tensors*256 && base<=size && load64(data+24)==size-base,"invalid checkpoint directory");
    let found=0;let i=0;while i<tensors {let row=data+32+i*256;vc_require(!load8(row+191),"unterminated tensor name");if pl_equal(row,"memory.weight_ih_T") {vc_require(!found,"duplicate recurrent input tensor");found=row;}i=i+1;}
    vc_require(found && load64(found+192)==2 && load64(found+200)==263*768 && load64(found+216)==263 && load64(found+224)==768,"expected 256-memory recurrent input tensor");
    let offset=load64(found+208);let bytes=263*768*4;vc_require(offset>=0 && offset<=size-base && bytes<=size-base-offset,"recurrent tensor exceeds checkpoint");
    let first=base+offset+256*768*4;let removed=5*768*4;vc_require(first>=base && first+removed<=size,"drive feedback rows exceed checkpoint");
    i=0;while i<removed {vc_require(!load8(data+first+i),"drive feedback weights are not zero");i=i+1;}
    let text=alloc(1024);let b=alloc(32);pl_builder(b,text,1024);pl_text(b,"{\"passed\":true,\"weightsSHA256\":");pj_text(b,vc_digest(data,size));pl_text(b,",\"tensor\":\"memory.weight_ih_T\",\"firstByte\":");pl_int(b,first);pl_text(b,",\"bytesChecked\":");pl_int(b,removed);pl_text(b,",\"driveFeedbackValuesZero\":5}\n");vc_require(!load64(b+24),"zero-weight report overflow");vc_write(report,text,load64(b+8));syscall(11,data,size,0,0,0,0);return 0;
}
