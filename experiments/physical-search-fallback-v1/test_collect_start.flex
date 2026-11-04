// Appended to an isolated candidate copy: only hardware/sensor calls are mocked.
fn sc_require(ok,message) { if !ok { pl_print(2,message);pl_print(2,"\n");syscall(231,1,0,0,0,0,0); } return 0; }
fn main(argc,argv) {
    if !pl_init() { return 2; }
    ps_agent_physical=1;ps_agent_oracle=0;ps_nav_training_oracle=0;ps_search_fallback_enabled=1;
    ps_collect_enabled=1;ps_discovery_enabled=1;ps_seek_enabled=0;ps_local_mode=2;ps_camera_drive_mode=1;
    ps_physical_owner=0;ps_physical_ack=0;ps_total=100;ps_brick_frame=100;ps_brick_count=0;
    ps_trace=alloc(2048);ps_nav_map=alloc(32);ps_discovery_observed=alloc(32);ps_collect_points=alloc(64);ps_case_target=alloc(32);
    store8(ps_nav_map,17);store8(ps_discovery_observed,19);store8(ps_collect_points,23);store8(ps_case_target,29);
    ps_collect_local_map=0;ps_collect_count=0;ps_collect_map_until=1;ps_house_ready=0;ps_discovery_scans=0;
    ps_discovery_motion_count=3;ps_discovery_retrace=1;sc_applied=0;
    sc_require(ps_physical_search_only() && ps_physical_owner==1 && ps_physical_ack==8,"real collector start rejected");
    sc_require(sc_applied==1 && ps_case_stage==26 && ps_discovery_phase==1 && ps_discovery_full,"real collector discovery state missing");
    sc_require(!ps_discovery_motion_count && !ps_discovery_retrace && !ps_collect_count,"real collector retained stale state");
    sc_require(load8(ps_nav_map)==17 && load8(ps_discovery_observed)==19 && load8(ps_collect_points)==23 && load8(ps_case_target)==29,"real collector wrote target or floor without evidence");
    pl_print(1,"Physical real collector-start CPU probe passed.\n");return 0;
}
