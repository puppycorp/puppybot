// Re-run the training-only coverage oracle for one original simulator scene.
// Only the saved, masked RGB/feedback and teacher label are exported.
import "../../../flex/control/correction.flex";
import "../../../flex/control/actions.flex";
import "../../../flex/control/augmentation.flex";

fn ci_result(output,action,input) {
    let text=alloc(4096);let b=alloc(32);pl_builder(b,text,4096);pl_text(b,"{\"runtime\":\"Flexscript\",\"actorInputSHA256\":");pj_text(b,vc_digest(input,21196));
    pl_text(b,",\"actorRGBSHA256\":");pj_text(b,vc_digest(input,21168));pl_text(b,",\"initialPose\":[");let i=0;
    while i<3 {if i {pl_char(b,44);}pl_float(b,load64(ve_initial_pose+i*8));i=i+1;}
    pl_text(b,"],\"coverageIndex\":");pl_int(b,vw_coverage_index);pl_text(b,",\"goal\":[");i=0;while i<3 {if i {pl_char(b,44);}pl_float(b,load64(ve_oracle_goal+i*8));i=i+1;}
    pl_text(b,"],\"action\":[");pl_float(b,pb_read_float(action));pl_char(b,44);pl_float(b,pb_read_float(action+4));pl_text(b,"],\"actionClass\":");pl_int(b,ca_class(pb_read_float(action),pb_read_float(action+4)));
    pl_text(b,",\"source\":");if vw_coverage_source==1 {pj_text(b,"camera");}else {pj_text(b,"coverage");}
    pl_text(b,",\"teacherUsesPrivilegedGeometry\":true,\"actorInputsUnchanged\":true,\"teacherLabelOnly\":true,\"autonomousSuccessClaimed\":false}\n");
    vc_require(!load64(b+24),"coverage initial report exceeded limit");ve_close();vc_write(vc_path(output,"result.json"),text,load64(b+8));return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==4,"coverage-initial-query SIMULATOR SCENE NEW_OUTPUT");
    let binary=vc_absolute(load64(argv+8));let scene=vc_absolute(load64(argv+16));let output=vc_absolute(load64(argv+24));
    ve_open_buffers();ve_teacher_oracle=1;vw_coverage_teacher=1;ve_open(binary,output,scene,0,1,0);vw_correction_reset();
    let action=alloc(8);vc_require(vw_coverage_action(action),"coverage teacher could not produce an initial label");let input=alloc(21196);vc_copy(input,ve_image,21168);vc_copy(input+21168,ve_feedback,28);pf_neutral_drive(input+21168);
    vc_require(ca_class(pb_read_float(action),pb_read_float(action+4))>=0,"coverage teacher produced a non-categorical action");return ci_result(output,action,input);
}
