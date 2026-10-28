// Validate target supervision against its complete source data and receipt.
import "../../../flex/control/target-supervision.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==4,"preflight-expanded-targets DATA TARGETS OUTPUT");let path=vc_absolute(load64(argv+8));let data=vd_map(path);let bytes=vc_size;
    vc_require(bytes>=32 && vd_row_bytes(data)==56,"invalid dense dataset header");let n=load64(data+8);let fit=load64(data+16);let length=load64(data+24);
    vc_require(n>=2 && n<=vd_episode_limit(data) && fit>=1 && fit<n && length>=1 && length<=512 && bytes==32+n*length*21224,"invalid dense dataset dimensions");pt_target_open(vc_absolute(load64(argv+16)),data,bytes,56);
    let text=alloc(1024);let b=alloc(32);pl_builder(b,text,1024);pl_text(b,"{\"passed\":true,\"runtime\":\"Flexscript\",\"episodes\":");pl_int(b,n);pl_text(b,",\"fittingHistories\":");pl_int(b,fit);pl_text(b,",\"validationHistories\":");pl_int(b,n-fit);pl_text(b,",\"sourceDataSHA256\":");pj_text(b,vc_digest(data,bytes));pl_text(b,",\"actorInputsUnchanged\":true}\n");vc_require(!load64(b+24),"preflight report exceeded limit");vc_write(vc_absolute(load64(argv+24)),text,load64(b+8));return 0;
}
