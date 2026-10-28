// Reproduce an oracle root edge that jumps across a box corner between samples.
import "../../build/flex/control/sim-test-library.flex";
import "../control/scene.flex";
fn cm_fixture(output) {
    let scene=vc_path(output,"case.json");let environment=vc_path(output,"environment.bin");vc_case(scene,"flex/sim/cases/find-return-house.json",8800706,1);vc_environment(environment,1);
    vc_require(ps_catalog_load(),"motion catalog failed");let index=ps_case_file(scene);vc_require(index>=0 && ps_case_load(index) && ps_environment_load(environment) && ps_model_load("build/flex/sim/puppybot.bin"),"motion fixture load failed");
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);ps_agent_fd=1;
    vc_require(ps_reset(),"motion fixture reset failed");
    // This tests collision geometry, without sampling RGB or starting a GUI.
    // The case-start renderer check is irrelevant to the driving arm pose.
    let camera=ps_case_camera;ps_case_camera=0;vc_require(ps_case_start(),"motion fixture start failed");ps_case_camera=camera;let tick=0;
    while tick<2500 && (!ps_camera_still() || !ps_pickup_settled() || ps_gripper_gap!=ps_gripper_goal) {vc_require(ps_tick(0),"motion fixture settling failed");tick=tick+1;}
    vc_require(ps_camera_still() && ps_pickup_settled(),"motion fixture arm did not settle");
    ps_x=vc_number(238662815,1000000000);ps_y=vc_number(57745816,1000000000);ps_heading=vc_number(-29841816,1000000000);
    ps_model_update(ps_robot,ps_plant,ps_x,ps_y,ps_heading,ps_wheel);ps_vehicle_init();ps_gripper_frame_update(ps_robot,ps_plant);vc_require(ps_contacts(ps_robot,ps_plant) && ps_nav_init(),"motion fixture geometry failed");ps_vehicle_planning=1;return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2,"visual-control-motion NEW_OUTPUT");let output=vc_absolute(load64(argv+8));vc_mkdir(output);cm_fixture(output);
    let a=ps_nav_actions+2*128;let c=f64_cos(ps_heading);let s=f64_sin(ps_heading);let sample=0;
    while sample<5 {let dx=load64(a+24+sample*16);let dy=load64(a+32+sample*16);let x=f64_add(ps_x,f64_sub(f64_mul(c,dx),f64_mul(s,dy)));let y=f64_add(ps_y,f64_add(f64_mul(s,dx),f64_mul(c,dy)));let h=f64_add(ps_heading,f64_mul(load64(a+16),vc_number(sample+1,5)));
        vc_require(ps_vehicle_free(x,y,h),"fixture no longer reproduces a missed inter-sample collision");sample=sample+1;
    }
    vc_require(!ps_vehicle_primitive_free(ps_x,ps_y,ps_heading,a) && ps_vehicle_hit==ps_case_bin_body,"teacher primitive swept through the physical box");
    vc_require(ps_vehicle_primitive_free(ps_x,ps_y,ps_heading,ps_nav_actions+4*128),"swept teacher guard rejected the clear straight reverse escape");
    ps_nav_training_oracle=1;ps_local_mode=0;let target=ph_body(ps_physics,3);vc_require(ps_nav_plan(f64_sub(pb_f32_to_f64(load64(target+8)),vc_number(24,100)),pb_f32_to_f64(load64(target+16)),0) && ps_nav_path_count>0,"teacher could not find an alternate physical route");
    let first=load64(ps_nav_path+(ps_nav_path_count-1)*8);vc_require(ps_vehicle_primitive_free(ps_x,ps_y,ps_heading,ps_nav_actions+first*128),"teacher selected a physically blocked first primitive");
    let request=alloc(64);let reply=alloc(64);store64(request+16,vc_number(2,1));store64(request+40,1);vc_require(!ps_agent_primitive_read(request,reply),"continuation without a preceding plan was accepted");
    // Two synthetic safe reverse primitives exercise route continuity.
    ps_nav_path_count=2;store64(ps_nav_path,4);store64(ps_nav_path+8,4);
    store64(reply+16,1);store64(reply+32,-1000);store64(reply+40,20);vc_require(ps_agent_primitive_save(request,reply),"teacher primitive could not be retained");let p=ps_agent_primitive;
    // Place the fixture at the predicted ten-tick midpoint, then exercise the
    // continuation protocol and its invalidation conditions independently.
    ps_x=load64(p+48);ps_y=load64(p+56);ps_heading=load64(p+64);ps_total=load64(p+24)+10;ps_agent_blocked=0;
    ps_model_update(ps_robot,ps_plant,ps_x,ps_y,ps_heading,ps_wheel);ps_vehicle_init();ps_gripper_frame_update(ps_robot,ps_plant);vc_require(ps_contacts(ps_robot,ps_plant),"continuation fixture failed");
    vc_require(ps_agent_primitive_read(request,reply) && load64(reply+32)== -1000 && load64(reply+40)==10,"remaining safe half-primitive was not preserved");
    ps_agent_primitive_advance(reply,1);ps_x=load64(p+48);ps_y=load64(p+56);ps_heading=load64(p+64);ps_total=load64(p+24)+10;
    ps_model_update(ps_robot,ps_plant,ps_x,ps_y,ps_heading,ps_wheel);ps_vehicle_init();ps_gripper_frame_update(ps_robot,ps_plant);vc_require(ps_contacts(ps_robot,ps_plant),"route continuation fixture failed");
    vc_require(ps_agent_primitive_read(request,reply) && load64(reply+32)== -1000 && load64(reply+40)==20,"completed primitive discarded the remaining safe route");
    let bin=ph_body(ps_physics,ps_case_bin_body);let saved=alloc(24);pb_copy(saved,bin+8,24);store64(bin+8,pb_f64_to_f32(vc_number(-12,100)));store64(bin+16,pb_f64_to_f32(vc_number(6,100)));let shape=1;
    while shape<ps_wheel_shape {let s=ph_shape(ps_physics,shape);if load64(s)==ps_case_bin_body {ph_cache_shape(ps_physics,s);}shape=shape+1;}
    vc_require(!ps_agent_primitive_read(request,reply),"changed physical world reused a blocked route edge");pb_copy(bin+8,saved,24);shape=1;
    while shape<ps_wheel_shape {let s=ph_shape(ps_physics,shape);if load64(s)==ps_case_bin_body {ph_cache_shape(ps_physics,s);}shape=shape+1;}
    vc_require(ps_agent_primitive_read(request,reply),"restored physical world did not permit its safe route");
    ps_x=f64_add(ps_x,vc_number(1,1000));vc_require(!ps_agent_primitive_read(request,reply),"deviated physical pose continued an obsolete plan");ps_x=load64(p+48);
    store64(request+16,vc_number(21,10));vc_require(!ps_agent_primitive_read(request,reply),"changed goal continued an obsolete plan");store64(request+16,vc_number(2,1));
    ps_agent_blocked=1;vc_require(!ps_agent_primitive_read(request,reply),"contact continued an obsolete plan");ps_agent_blocked=0;
    ps_total=ps_total+1;vc_require(!ps_agent_primitive_read(request,reply),"wrong physics interval continued an obsolete plan");ps_total=ps_total-1;
    store64(request+40,0);vc_require(!ps_agent_primitive_read(request,reply),"fresh planning request was replaced by a continuation");
    vc_save_text(vc_path(output,"result.json"),"{\"passed\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"coarseEndpointsMissPhysicalBox\":true,\"sweptPrimitiveRejectsBox\":true,\"clearReverseEscapeAccepted\":true,\"teacherChoosesExecutableFirstPrimitive\":true,\"physicalGuardResolutionM\":0.001,\"safeTenTickContinuationAccepted\":true,\"safeRouteContinuationAccepted\":true,\"changedWorldInvalidatesRoute\":true,\"continuationRequiresMatchingPoseGoalContactAndInterval\":true,\"freshPlanningRemainsAvailable\":true}\n");pl_print(1,"Native teacher swept collision and route continuation checks passed.\n");return 0;
}
