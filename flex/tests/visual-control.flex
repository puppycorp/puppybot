// Native visual-control contract tests; deliberately no Python test oracle.
import "../control/oracle.flex";
fn vt_resize() {
    let rgb=alloc(921600);let out=alloc(168*168*3);let y=0;
    while y<480 {let x=0;while x<640 {let p=rgb+(y*640+x)*3;if x<320 {store8(p,255);}else {store8(p+2,255);}if y<240 {store8(p+1,255);}x=x+1;}y=y+1;}
    vc_resize(rgb,out);y=0;while y<84 {let x=0;while x<84 {vc_require(load8(out+y*84+x)==255*(x<42),"area resize red/channel order");
        vc_require(load8(out+7056+y*84+x)==255*(y<42),"area resize vertical coverage");vc_require(load8(out+14112+y*84+x)==255*(x>=42),"area resize blue/channel order");x=x+1;}y=y+1;}
    let size=128;while size<=168 {vc_resize_to(rgb,out,size);y=0;while y<size {let x=0;while x<size {vc_require(load8(out+y*size+x)==255*(x<size/2),"larger area resize red/channel order");vc_require(load8(out+size*size+y*size+x)==255*(y<size/2),"larger area resize vertical coverage");vc_require(load8(out+2*size*size+y*size+x)==255*(x>=size/2),"larger area resize blue/channel order");x=x+1;}y=y+1;}size=size+40;}
    pb_zero(rgb,921600);store8(rgb,255);vc_resize(rgb,out);vc_require(load8(out)==6,"area integration of a single source pixel");let i=1;while i<21168 {vc_require(!load8(out+i),"single pixel leaked into another output cell");i=i+1;}
    size=128;while size<=168 {vc_resize_to(rgb,out,size);let expected=14;if size==168 {expected=23;}vc_require(load8(out)==expected,"larger area integration of a single source pixel");i=1;while i<size*size*3 {vc_require(!load8(out+i),"single pixel leaked into larger output cells");i=i+1;}size=size+40;}
    syscall(11,rgb,921600,0,0,0,0);syscall(11,out,168*168*3,0,0,0,0);return 0;
}
fn vt_boundary() {
    let text="{\"pose\":[999,-999,3],\"objects\":[{\"position\":[77,88,99]}],\"map\":[1,1,1],\"drive\":{\"leftSpeed\":-12,\"rightSpeed\":-12,\"steeringAngleDeg\":73}}";
    let root=pj_parse(text,pl_size(text));vc_require(root,"boundary fixture JSON");let previous=alloc(8);pb_put32(previous,pb_f64_to_f32(vc_number(1,10)));pb_put32(previous+4,pb_f64_to_f32(vc_number(-3,10)));let a=alloc(28);let b=alloc(28);
    vc_feedback(pj_get(root,"drive"),previous,1,a);let pose=pj_get(root,"pose");vc_set_number(pj_index(pose,0),vc_number(-1,100));vc_set_number(pj_index(pose,1),vc_number(99,100));
    vc_feedback(pj_get(root,"drive"),previous,1,b);let i=0;while i<28 {vc_require(load8(a+i)==load8(b+i),"reference fields changed actor observation");i=i+1;}
    vc_require(!pb_u32(a+24) && pb_u32(a+20)==0x3f800000,"task hint/contact boundary");
    vc_require(f64_lt(f64_magnitude(f64_sub(pb_read_float(a+8),vc_number(-12,100))),vc_number(1,1000000)),"wheel feedback normalization");
    let image=alloc(21168);let hidden=alloc(512);let input=alloc((21168+7+128)*4);store8(image,255);pb_put32(hidden,0x3f000000);vc_pixels_init();vc_policy_input(image,a,hidden,input,0);
    vc_require(pb_u32(input)==0x3f800000 && pb_u32(input+4)==0 && pb_u32(input+(21168+7)*4)==0x3f000000,"native policy input packing");vc_policy_input(image,a,hidden,input,1);vc_require(!pb_u32(input) && pb_u32(input+(21168+7)*4)==0x3f000000,"blackout changed memory or failed to mask image");return 0;
}
fn vt_scene(directory) {
    vc_environment(vc_path(directory,"environment.bin"),0);let data=vc_map(vc_path(directory,"environment.bin"));vc_require(load64(data)==load64("PBENV001") && load64(data+8)==4 && load64(data+16)==180,"native curriculum world format");
    vc_require(load64(data+256+96)==0,"world yaw accidentally includes collision flags");syscall(11,data,vc_size,0,0,0,0);
    vc_case(vc_path(directory,"case-a.json"),"flex/sim/cases/find-return-house.json",71001,0);vc_case(vc_path(directory,"case-b.json"),"flex/sim/cases/find-return-house.json",71001,0);
    vc_require(pl_equal(vc_file_sha(vc_path(directory,"case-a.json")),vc_file_sha(vc_path(directory,"case-b.json"))),"scene seed is not reproducible");let root=vc_json_file(vc_path(directory,"case-a.json"));vc_require(pj_count(pj_get(root,"objects"))==1 && pj_boolean(pj_get(root,"container"),"fixed"),"curriculum object/container contract");let positive=0;let negative=0;let seed=0;
    while seed<32 {vc_case(vc_path(directory,"balanced.json"),"flex/sim/cases/find-return-house.json",410000+seed*2,0);root=vc_json_file(vc_path(directory,"balanced.json"));let y=pj_real_node(pj_index(pj_get(pj_get(root,"container"),"position"),1));if f64_gt(y,0) {positive=positive+1;}else {negative=negative+1;}seed=seed+1;}
    vc_require(positive>0 && negative>0,"mixed curriculum coupled box side to difficulty");return 0;
}
fn vt_oracle(directory) {
    let world=vc_path(directory,"oracle");vc_mkdir(world);let scene=vc_path(world,"scene");vc_mkdir(scene);vc_environment(vc_path(scene,"environment.bin"),1);vc_case(vc_path(scene,"case.json"),"flex/sim/cases/find-return-house.json",71002,1);
    ve_pose=alloc(24);ve_state=pj_parse("{\"marker\":123}",14);vo_open(world);vc_require(vc_json_int(ve_state,"marker",0)==123,"oracle reference parsing changed the live observation");
    vc_require(vo_count>30 && !vo_line(0,0,vo_target_x,vo_target_y),"oracle hidden target route must avoid the partition");let i=1;
    while i<vo_count {vc_require(vo_line(load64(vo_route+(i-1)*16),load64(vo_route+(i-1)*16+8),load64(vo_route+i*16),load64(vo_route+i*16+8)),"oracle route crosses an inflated obstacle");i=i+1;}
    let action=alloc(8);let history=alloc(16);ve_found=0;vo_action(action,history,0,0,vc_number(7,10));vc_require(f64_gt(pb_read_float(action+4),0),"oracle failed to drive toward its route");ve_found=1;vo_action(action,history,1,0,vc_number(7,10));vc_require(f64_lt(pb_read_float(action+4),0),"oracle failed to reverse the demonstrated path");vo_action(action,history,1,1,vc_number(7,10));vc_require(!load64(action),"oracle failed to stop for docking");vo_close();return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2,"visual-control-tests NEW_OUTPUT_DIRECTORY");let output=vc_absolute(load64(argv+8));vc_mkdir(output);
    vc_require(pl_equal(vc_digest("abc",3),"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),"native SHA256 contract");
    vt_resize();vt_boundary();vt_scene(output);vt_oracle(output);vc_save_text(vc_path(output,"result.json"),"{\"passed\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"checks\":[\"exact-area resize\",\"RGB/NCHW channels\",\"reference input isolation\",\"masked task hint\",\"blackout\",\"policy input packing\",\"deterministic scene\",\"native environment format\",\"oracle wall avoidance\",\"oracle reference isolation\",\"oracle return and stop\",\"SHA256\"]}\n");
    pl_print(1,"Native visual-control observation/scene contracts passed.\n");return 0;
}
