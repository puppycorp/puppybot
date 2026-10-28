// Collect coverage-teacher search labels on a recorded, exactly replayed
// history. The label trace is a candidate; it does not change the dataset.
import "coverage-replay-support.flex";

fn cl_result(output,count,supervised,commands,matched,reason) {
    let text=alloc(4096);let b=alloc(32);pl_builder(b,text,4096);pl_text(b,"{\"runtime\":\"Flexscript\",\"searchLabels\":");pl_int(b,count);pl_text(b,",\"originallySupervisedLabels\":");pl_int(b,supervised);
    pl_text(b,",\"replayedCommands\":");pl_int(b,commands);pl_text(b,",\"observationFramesMatched\":");pl_int(b,matched);pl_text(b,",\"termination\":");pj_text(b,reason);
    pl_text(b,",\"teacherSearchSHA256\":");pj_text(b,vc_file_sha(vc_path(output,"teacher-search.jsonl")));pl_text(b,",\"teacherUsesPrivilegedGeometry\":true,\"actorInputsUnchanged\":true,\"recordedActionsReplayed\":true,\"teacherLabelsOnly\":true,\"datasetModified\":false,\"autonomousSuccessClaimed\":false}\n");
    vc_require(!load64(b+24),"coverage relabel report exceeded limit");vc_write(vc_path(output,"result.json"),text,load64(b+8));return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==8,"coverage-relabel-search SIMULATOR SCENE RECORDING DATA EPISODE MAX_LABELS NEW_OUTPUT");
    let binary=vc_absolute(load64(argv+8));let scene=vc_absolute(load64(argv+16));let run=vc_absolute(load64(argv+24));let data=vc_absolute(load64(argv+32));
    let episode=pl_integer(load64(argv+40),pl_size(load64(argv+40)));vc_require(!pl_bad_number,"invalid packed episode");cr_load(data,episode);
    let limit=pl_integer(load64(argv+48),pl_size(load64(argv+48)));vc_require(!pl_bad_number && limit>=1 && limit<=cr_length,"invalid label limit");let output=vc_absolute(load64(argv+56));cr_open(binary,scene,run,output);
    vw_coverage_trace=syscall(2,vc_path(output,"teacher-search.jsonl"),0x800c1,384,0,0,0);vc_require(vw_coverage_trace>=0,"cannot create teacher label trace");
    let teacher=alloc(8);let executed=alloc(8);let time=0;let labels=0;let supervised=0;let commands=0;let matched=0;let reason="end-of-history";let active=1;
    while active && time<cr_length {
        let packed=cr_row(time);if !pb_u32(packed+44) {active=0;}
        else {
            cr_check_observation(run,time);matched=matched+1;
            if ve_found {reason="return-phase";active=0;}
            else if labels>=limit {reason="label-limit";active=0;}
            else if !vw_coverage_action(teacher) {reason="teacher-unavailable";active=0;}
            else {
                vc_require(ca_class(pb_read_float(teacher),pb_read_float(teacher+4))>=0,"coverage teacher produced a non-categorical action");vw_coverage_record(teacher);labels=labels+1;if pb_u32(packed+40) {supervised=supervised+1;}
                if time+1>=cr_length || !pb_u32(cr_row(time+1)+44) {active=0;}
                else if labels>=limit {reason="label-limit";active=0;}
                else {cr_replay_action(time,executed);commands=commands+1;time=time+1;}
            }
        }
    }
    syscall(3,vw_coverage_trace,0,0,0,0,0);vw_coverage_trace=0;ve_close();vc_require(labels>0,"coverage teacher produced no search labels");return cl_result(output,labels,supervised,commands,matched,reason);
}
