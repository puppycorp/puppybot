// Reconstruct a recorded observation history and query the training-only
// coverage teacher at the requested pre-action frame. No policy is run.
import "coverage-replay-support.flex";

fn cr_write(output,action,time) {
    let text=alloc(4096);let b=alloc(32);pl_builder(b,text,4096);pl_text(b,"{\"runtime\":\"Flexscript\",\"decision\":");pl_int(b,time);pl_text(b,",\"replayedCommands\":");pl_int(b,time);
    pl_text(b,",\"observationFramesMatched\":");pl_int(b,time+1);pl_text(b,",\"actorRGBSHA256\":");pj_text(b,vc_digest(ve_image,21168));let packed=cr_base+cr_length*21168+time*56;vc_require(pb_u32(packed+40)==0x3f800000,"requested packed frame has no teacher label");pl_text(b,",\"corpusActionClass\":");pl_int(b,ca_class(pb_read_float(packed+28),pb_read_float(packed+32)));pl_text(b,",\"coverageIndex\":");pl_int(b,vw_coverage_index);pl_text(b,",\"goal\":[");let i=0;
    while i<3 {if i {pl_char(b,44);}pl_float(b,load64(ve_oracle_goal+i*8));i=i+1;}pl_text(b,"],\"action\":[");pl_float(b,pb_read_float(action));pl_char(b,44);pl_float(b,pb_read_float(action+4));pl_text(b,"],\"actionClass\":");pl_int(b,ca_class(pb_read_float(action),pb_read_float(action+4)));
    pl_text(b,",\"source\":");if vw_coverage_source==1 {pj_text(b,"camera");}else {pj_text(b,"coverage");}
    pl_text(b,",\"teacherUsesPrivilegedGeometry\":true,\"actorInputsUnchanged\":true,\"recordedActionsReplayed\":true,\"teacherLabelOnly\":true,\"autonomousSuccessClaimed\":false}\n");
    vc_require(!load64(b+24),"coverage replay report exceeded limit");ve_close();vc_write(vc_path(output,"result.json"),text,load64(b+8));return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==8,"coverage-replay-query SIMULATOR SCENE RECORDING DATA EPISODE DECISION NEW_OUTPUT");
    let binary=vc_absolute(load64(argv+8));let scene=vc_absolute(load64(argv+16));let run=vc_absolute(load64(argv+24));let data=vc_absolute(load64(argv+32));let episode=pl_integer(load64(argv+40),pl_size(load64(argv+40)));vc_require(!pl_bad_number,"invalid packed episode");cr_load(data,episode);
    let time=pl_integer(load64(argv+48),pl_size(load64(argv+48)));vc_require(!pl_bad_number && time>=0 && time<cr_length,"invalid replay decision");let output=vc_absolute(load64(argv+56));cr_open(binary,scene,run,output);
    let teacher=alloc(8);let executed=alloc(8);let i=0;while i<=time {
        cr_check_observation(run,i);vc_require(!ve_found && vw_coverage_action(teacher),"coverage teacher could not label a replayed search frame");vc_require(ca_class(pb_read_float(teacher),pb_read_float(teacher+4))>=0,"coverage teacher produced a non-categorical action");
        if i<time {cr_replay_action(i,executed);}
        i=i+1;
    }
    return cr_write(output,teacher,time);
}
