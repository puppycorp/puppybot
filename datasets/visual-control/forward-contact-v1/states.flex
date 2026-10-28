// Count the actual pre-action states supplied to the student during roll-in.
import "../../../flex/control/dataset.flex";
import "../../../flex/control/actions.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==4,"states DATA RUN OUTPUT_JSON");let data=vc_map(load64(argv+8));let bytes=vc_size;let run=vc_absolute(load64(argv+16));let n=load64(data+8);let fit=load64(data+16);let length=load64(data+24);vc_require(vd_row_bytes(data)==56 && n>=2 && n<=256 && fit>=1 && fit<n && length>=1 && length<=354 && bytes==32+n*length*21224,"invalid contact coverage dataset");
    let counts=alloc(7*8);let frames=0;let fitting_commands=0;let student=0;let reverse=0;let episode=0;
    while episode<n {let base=data+32+episode*length*21224;let meta=vc_json_file(vc_path(vc_path(run,vc_concat("expert-",vc_int(episode))),"supervision.json"));let window=vc_json_int(meta,"studentActions",0);vc_require(window>=0 && window<=length && !vc_json_int(meta,"studentStartAction",0),"invalid prefix window");student=student+window;if episode<fit {fitting_commands=fitting_commands+window;}let t=0;
        while t<window {let row=base+length*21168+t*56;vc_require(pb_u32(row+44)==0x3f800000 && pb_u32(row+40)==0x3f800000 && !pb_u32(row+24),"invalid student input or supervision mask");if episode<fit && !pb_u32(row+36) && pb_u32(row+20) && f64_gt(pb_read_float(row+4),0) {let kind=ca_class(pb_read_float(row+28),pb_read_float(row+32));vc_require(kind>=0,"unsupported contact target");frames=frames+1;store64(counts+kind*8,load64(counts+kind*8)+1);if f64_lt(pb_read_float(row+32),0) {reverse=reverse+1;}}t=t+1;
        }episode=episode+1;
    }
    let text=alloc(2048);let b=alloc(32);pl_builder(b,text,2048);pl_text(b,"{\"episodes\":");pl_int(b,n);pl_text(b,",\"fittingHistories\":");pl_int(b,fit);pl_text(b,",\"studentCommands\":");pl_int(b,student);pl_text(b,",\"fittingStudentCommands\":");pl_int(b,fitting_commands);pl_text(b,",\"fittingForwardContactFrames\":");pl_int(b,frames);pl_text(b,",\"fittingForwardContactReverseLabels\":");pl_int(b,reverse);pl_text(b,",\"fittingForwardContactTargetCounts\":[");let i=0;while i<7 {if i {pl_char(b,44);}pl_int(b,load64(counts+i*8));i=i+1;}pl_text(b,"],\"dataSHA256\":");pj_text(b,vc_digest(data,bytes));pl_text(b,"}\n");vc_require(!load64(b+24),"state coverage report overflow");vc_write(load64(argv+24),text,load64(b+8));return 0;
}
