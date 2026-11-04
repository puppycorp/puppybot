// Appended to an isolated copy of transformed sim/main.flex for CPU-only tests.
fn ph_hint_require(ok,message) { if !ok { pl_print(2,message); pl_print(2,"\n"); syscall(231,1,0,0,0,0,0); } return 0; }
fn ph_hint_setup() {
    ps_plant=alloc(2048);ps_bus=alloc(2048);pb_zero(ps_plant,2048);pb_zero(ps_bus,2048);store64(ps_plant+8,ps_bus);
    ps_brick_records=alloc(256);pb_zero(ps_brick_records,256);ps_brick_count=1;
    store64(ps_brick_records,10);store64(ps_brick_records+8,10);store64(ps_brick_records+16,30);store64(ps_brick_records+24,30);
    store64(ps_brick_records+32,ps_number(1,2));store64(ps_brick_records+40,0);store64(ps_brick_records+48,0);store64(ps_brick_records+64,1);
    ps_collect_enabled=1;ps_agent_physical=1;ps_physical_owner=0;ps_seek_enabled=0;ps_local_mode=2;ps_camera_drive_mode=1;
    ps_local_x=0;ps_local_y=0;ps_total=100;ps_brick_frame=100;ps_handoff_hint_enabled=1;ps_collect_reset();return 0;
}
fn main(argc,argv) {
    if !pl_init() { return 2; } ph_hint_setup();
    ps_handoff_hint_enabled=0;ph_hint_require(!ps_handoff_hint_capture() && !ps_collect_count,"disabled hint changed state");
    ps_handoff_hint_enabled=1;ps_brick_frame=99;ph_hint_require(!ps_handoff_hint_capture(),"stale frame accepted");ps_brick_frame=100;
    ps_brick_count=0;ph_hint_require(!ps_handoff_hint_capture(),"empty detection accepted");ps_brick_count=1;
    ps_local_mode=0;ph_hint_require(!ps_handoff_hint_capture(),"oracle localization accepted");ps_local_mode=2;
    ps_camera_drive_mode=0;ph_hint_require(!ps_handoff_hint_capture(),"wrong camera pose accepted");ps_camera_drive_mode=1;
    ps_agent_physical=0;ph_hint_require(!ps_handoff_hint_capture(),"virtual protocol accepted");ps_agent_physical=1;
    ps_physical_owner=1;ph_hint_require(!ps_handoff_hint_capture(),"collector-owned capture accepted");ps_physical_owner=0;
    store64(ps_plant+136,1);ph_hint_require(!ps_handoff_hint_capture(),"moving wrist accepted");store64(ps_plant+136,0);
    ph_hint_require(ps_handoff_hint_capture() && ps_handoff_hint_valid && !ps_collect_count,"fresh hint was not held separately");
    ph_hint_require(!ps_house_ready && !ps_collect_select(),"unconfirmed hint initiated pickup");
    ps_physical_owner=1;ps_total=110;ps_brick_frame=110;ph_hint_require(ps_collect_sighting(ps_brick_records),"second sighting failed");
    ph_hint_require(ps_collect_count==1 && load64(ps_collect_points+32)==2 && ps_handoff_hint_uses==1,"hint did not seed exactly one prior frame");
    ps_collect_sighting(ps_brick_records);ph_hint_require(load64(ps_collect_points+32)==2,"same frame counted twice");
    ps_total=120;ps_brick_frame=120;ps_collect_sighting(ps_brick_records);ph_hint_require(load64(ps_collect_points+32)==3,"third distinct frame not confirmed");
    ps_house_ready=0;ph_hint_require(!ps_collect_select(),"pickup bypassed home localization");
    ps_house_ready=1;ps_collect_map_until=1;ps_discovery_scans=0;ph_hint_require(!ps_collect_select(),"pickup bypassed initial map");
    ps_collect_reset();ps_house_ready=0;ps_physical_owner=0;ps_total=200;ps_brick_frame=200;ph_hint_require(ps_handoff_hint_capture(),"hint reset failed");
    ps_physical_owner=1;ps_collect_sighting(ps_brick_records);ph_hint_require(load64(ps_collect_points+32)==1 && !ps_handoff_hint_uses,"same-frame hint double-counted");
    ps_total=210;ps_brick_frame=210;ps_collect_sighting(ps_brick_records);ps_handoff_hint_finish_observation();
    ph_hint_require(load64(ps_collect_points+32)==2 && !ps_handoff_hint_valid && !ps_handoff_hint_uses,"duplicate path gained extra count");
    ps_collect_reset();ps_physical_owner=0;ps_total=300;ps_brick_frame=300;ph_hint_require(ps_handoff_hint_capture(),"stale test capture failed");
    ps_physical_owner=1;ps_total=801;ps_brick_frame=801;ps_collect_sighting(ps_brick_records);ps_handoff_hint_finish_observation();
    ph_hint_require(load64(ps_collect_points+32)==1 && !ps_handoff_hint_valid && !ps_handoff_hint_uses,"expired hint affected memory");
    ps_collect_reset();ps_physical_owner=0;ps_total=900;ps_brick_frame=900;ph_hint_require(ps_handoff_hint_capture(),"mismatch test capture failed");
    ps_physical_owner=1;ps_total=910;ps_brick_frame=910;store64(ps_brick_records+64,2);ps_collect_sighting(ps_brick_records);ps_handoff_hint_finish_observation();
    ph_hint_require(load64(ps_collect_points+32)==1 && !ps_handoff_hint_valid && !ps_handoff_hint_uses,"different color credited old hint");
    ps_collect_reset();ps_physical_owner=0;ps_local_mode=2;ps_total=1000;ps_brick_frame=1000;store64(ps_brick_records+64,1);ph_hint_require(ps_handoff_hint_capture(),"lost-localization test capture failed");
    ps_physical_owner=1;ps_local_mode=0;ps_total=1010;ps_brick_frame=1010;ps_collect_sighting(ps_brick_records);ps_handoff_hint_finish_observation();
    ph_hint_require(load64(ps_collect_points+32)==1 && !ps_handoff_hint_uses,"hint accepted without local odometry");
    ps_collect_reset();ps_physical_owner=0;ps_local_mode=2;ps_total=1100;ps_brick_frame=1100;ph_hint_require(ps_handoff_hint_capture(),"empty next frame capture failed");
    ps_physical_owner=1;ps_total=1110;ps_brick_frame=1110;ps_brick_count=0;ps_handoff_hint_finish_observation();
    ph_hint_require(!ps_handoff_hint_valid && !ps_collect_count,"empty next frame did not discard hint");
    ps_collect_reset();ps_handoff_hint_enabled=0;ps_brick_count=1;ps_total=1200;ps_brick_frame=1200;ps_collect_sighting(ps_brick_records);
    ph_hint_require(load64(ps_collect_points+32)==1 && !ps_handoff_hint_uses,"disabled first observation changed");
    ps_collect_sighting(ps_brick_records);ph_hint_require(load64(ps_collect_points+32)==1,"disabled duplicate frame changed");
    ps_total=1210;ps_brick_frame=1210;ps_collect_sighting(ps_brick_records);ph_hint_require(load64(ps_collect_points+32)==2,"disabled second frame changed");
    // Exactly 500 ticks and under 6 cm are accepted; 501 ticks or over
    // 6 cm must not add the initial observation to a later sighting.
    ps_collect_reset();ps_physical_owner=0;ps_handoff_hint_enabled=1;ps_total=1300;ps_brick_frame=1300;ph_hint_require(ps_handoff_hint_capture(),"boundary hint capture failed");
    ps_physical_owner=1;ps_total=1800;ps_brick_frame=1800;store64(ps_brick_records+32,ps_number(559,1000));ps_collect_sighting(ps_brick_records);
    ph_hint_require(load64(ps_collect_points+32)==2 && ps_handoff_hint_uses==1,"valid age/distance boundary rejected");
    ps_collect_reset();ps_physical_owner=0;ps_total=1900;ps_brick_frame=1900;store64(ps_brick_records+32,ps_number(1,2));ph_hint_require(ps_handoff_hint_capture(),"distance test capture failed");
    ps_physical_owner=1;ps_total=1910;ps_brick_frame=1910;store64(ps_brick_records+32,ps_number(561,1000));ps_collect_sighting(ps_brick_records);ps_handoff_hint_finish_observation();
    ph_hint_require(load64(ps_collect_points+32)==1 && !ps_handoff_hint_valid && !ps_handoff_hint_uses,"distant detection credited old hint");
    pl_print(1,"Physical RGB handoff hint CPU probe passed.\n");return 0;
}
