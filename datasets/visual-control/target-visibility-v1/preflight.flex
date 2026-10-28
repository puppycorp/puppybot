// Validate the complete target sidecar before any training starts.
import "../../../flex/control/target-supervision.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==4,"preflight DATA TARGET_DIRECTORY OUTPUT_JSON");let data=vc_map(vc_absolute(load64(argv+8)));let bytes=vc_size;let row_bytes=vd_row_bytes(data);vc_require(row_bytes,"invalid preflight data");pt_target_open(vc_absolute(load64(argv+16)),data,bytes,row_bytes);let out=alloc(1024);let b=alloc(32);pl_builder(b,out,1024);pl_text(b,"{\"passed\":true,\"sourceDataSHA256\":");pj_text(b,vc_digest(data,bytes));pl_text(b,",\"targetSHA256\":");let size=32+load64(data+8)*load64(data+24)*12;pj_text(b,vc_digest(pt_target_data,size));pl_text(b,",\"episodes\":");pl_int(b,load64(data+8));pl_text(b,",\"actorInputsUnchanged\":true}\n");vc_require(!load64(b+24),"target preflight output overflow");vc_write(vc_absolute(load64(argv+24)),out,load64(b+8));return 0;
}
