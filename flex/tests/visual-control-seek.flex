// Exercise the real consumption event for approach-only, return and UI tasks.
import "../../build/flex/control/sim-test-library.flex";
import "../control/host.flex";
fn sc_fixture(mode,x,y) {
    ps_agent_fd=mode!=0;ps_agent_task=mode;ps_x=0;ps_y=0;ps_heading=0;
    // Deliberately bias localization; the acceptance radius uses physical pose.
    ps_local_mode=1;ps_local_x=vc_number(10,1);ps_local_y=vc_number(-8,1);ps_local_heading=0;
    ps_seek_reset();store64(ps_case_objects+208,0);let body=ph_body(ps_physics,8);pb_zero(body,448);
    store64(body+8,pb_f64_to_f32(x));store64(body+16,pb_f64_to_f32(y));store64(body+24,pb_f64_to_f32(vc_number(13,1000)));store64(body+56,0x3f800000);
    // Point a synthetic world-space camera down at the physical prop, so the
    // proximity cases also satisfy the independent pixel-association check.
    let cx=f64_to_i64_nearest(f64_mul(x,f64_from_i64(1000)));let cy=f64_to_i64_nearest(f64_mul(y,f64_from_i64(1000)));
    store64(ps_eye,cx);store64(ps_eye+8,cy);store64(ps_eye+16,1000);store64(ps_target,cx);store64(ps_target+8,cy);store64(ps_target+16,0);store64(ps_up,1000000);store64(ps_up+8,0);store64(ps_up+16,0);ps_brick_frame=ps_total;
    let detection=alloc(128);store64(detection,318);store64(detection+8,238);store64(detection+16,322);store64(detection+24,242);store64(detection+32,f64_add(ps_local_x,x));store64(detection+40,f64_add(ps_local_y,y));return detection;
}
fn sc_check(mode,x,y,expected) {
    let detection=sc_fixture(mode,x,y);let result=ps_seek_consume(detection);let body=ph_body(ps_physics,8);
    vc_require(result==expected && ps_seek_found==expected && load64(ps_case_objects+208)==expected,"brick approach acceptance differs from the physical radius");
    if expected {vc_require(ps_seek_consumed==0 && f64_eq(pb_f32_to_f64(load64(body+24)),vc_number(-10,1)),"accepted brick was not consumed");}
    else {vc_require(ps_seek_consumed== -1 && f64_gt(pb_f32_to_f64(load64(body+24)),0),"distant visible brick changed task state or physics");}
    syscall(11,detection,128,0,0,0,0);return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2,"visual-control-seek NEW_OUTPUT");let output=vc_absolute(load64(argv+8));vc_mkdir(output);
    ps_physics=ph_world(16,16,8,0);ps_case_count=1;ps_case_objects=alloc(256);store64(ps_case_objects+184,8);ps_total=10;ps_eye=alloc(24);ps_target=alloc(24);ps_up=alloc(24);
    let mode=0;while mode<3 {
        sc_check(mode,vc_number(2,1),0,0);sc_check(mode,vc_number(36,100),0,0);sc_check(mode,vc_number(3501,10000),0,0);
        sc_check(mode,vc_number(25,100),vc_number(25,100),0);sc_check(mode,vc_number(35,100),0,1);sc_check(mode,vc_number(-35,100),0,1);sc_check(mode,vc_number(24,100),vc_number(24,100),1);
        let detection=sc_fixture(mode,vc_number(3,10),0);store64(detection+32,f64_add(load64(detection+32),vc_number(2,10)));vc_require(!ps_seek_consume(detection) && !ps_seek_found,"nearby brick without a matching RGB detection was consumed");syscall(11,detection,128,0,0,0,0);mode=mode+1;
    }
    let detection=sc_fixture(2,vc_number(3,10),0);store64(detection,0);store64(detection+8,0);store64(detection+16,10);store64(detection+24,10);vc_require(!ps_seek_consume(detection) && !ps_seek_found,"unrelated RGB region consumed a brick");
    store64(detection,318);store64(detection+8,238);store64(detection+16,322);store64(detection+24,242);ps_brick_frame=ps_total-1;vc_require(!ps_seek_consume(detection) && !ps_seek_found,"stale RGB frame consumed a brick");
    ps_brick_frame=ps_total;vc_require(ps_seek_consume(detection) && ps_seek_found,"fresh matching RGB frame did not consume the nearby brick");syscall(11,detection,128,0,0,0,0);
    // A closer but visually unrelated prop must not hide another candidate
    // whose projected center actually matches the observed region.
    ps_case_count=2;ps_case_objects=alloc(512);store64(ps_case_objects+184,8);store64(ps_case_objects+256+184,9);
    detection=sc_fixture(2,vc_number(20,100),0);let second=ph_body(ps_physics,9);pb_zero(second,448);store64(second+8,pb_f64_to_f32(vc_number(27,100)));store64(second+24,pb_f64_to_f32(vc_number(13,1000)));store64(second+56,0x3f800000);store64(ps_eye,270);store64(ps_target,270);
    vc_require(ps_seek_consume(detection) && ps_seek_consumed==1 && !load64(ps_case_objects+208),"a closer unrelated prop masked the visually matched prop");syscall(11,detection,128,0,0,0,0);
    vc_save_text(vc_path(output,"result.json"),"{\"passed\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"maximumBrickDistanceM\":0.35,\"modesChecked\":[\"autonomous\",\"approach-only\",\"find-return\"],\"physicalPoseWithBiasedLocalization\":true,\"farVisibleBrickPreserved\":true,\"justOutsideRejected\":true,\"boundaryAccepted\":true,\"diagonalRadiusChecked\":true,\"matchingDetectionRequired\":true,\"unrelatedAndStaleDetectionsRejected\":true,\"matchingPropChosenAmongMultiple\":true}\n");pl_print(1,"Native visible-brick proximity acceptance checks passed.\n");return 0;
}
