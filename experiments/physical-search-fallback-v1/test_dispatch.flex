// Appended only to a disposable candidate source copy with CPU sensor mocks.
fn sf_require(ok, message) { if !ok { pl_print(2,message);pl_print(2,"\n");syscall(231,1,0,0,0,0,0); } return 0; }
fn sf_reset() {
    ps_physical_owner=0;ps_physical_ack=0;ps_search_fallback_enabled=1;ps_agent_physical=1;ps_agent_oracle=0;ps_nav_training_oracle=0;ps_collect_enabled=1;ps_discovery_enabled=1;ps_seek_enabled=0;ps_local_mode=2;ps_camera_drive_mode=1;
    ps_total=100;ps_brick_frame=100;ps_brick_count=0;ps_collect_count=0;
    sf_mock_stop=1;sf_mock_rgb=1;sf_mock_detect=1;sf_mock_stale=0;sf_mock_collector=1;sf_mock_camera=1;sf_mock_count=0;sf_mock_samples=0;sf_mock_stops=0;
    return 0;
}
fn main(argc,argv) {
    if !pl_init() { return 2; }
    ps_collect_enabled=1;ps_agent_physical=1;ps_seek_enabled=0;ps_camera_drive_mode=1;
    ps_nav_map=alloc(32);ps_discovery_observed=alloc(32);ps_collect_points=alloc(64);ps_case_target=alloc(32);
    store8(ps_nav_map,17);store8(ps_discovery_observed,19);store8(ps_collect_points,23);store8(ps_case_target,29);
    sf_reset();
    sf_require(ps_physical_permit(1,0,8,0,0,0,4),"enabled search-only request rejected");
    sf_require(!ps_physical_permit(0,0,8,0,0,0,4) && !ps_physical_permit(1,1,8,0,0,0,4) && !ps_physical_permit(1,2,8,0,0,0,4),"search-only owner/init guard failed");
    sf_require(!ps_physical_permit(1,0,8,1,0,0,4) && !ps_physical_permit(1,0,8,0,1,0,4) && !ps_physical_permit(1,0,8,0,0,1,4) && !ps_physical_permit(1,0,8,0,0,0,3),"search-only argument guard failed");
    ps_search_fallback_enabled=0;sf_require(!ps_physical_permit(1,0,8,0,0,0,4),"disabled search-only request accepted");
    sf_require(ps_physical_permit(1,0,6,0,0,0,4),"ordinary handoff changed while disabled");
    sf_reset();ps_search_fallback_enabled=0;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"disabled direct search handler accepted");
    sf_reset();ps_physical_owner=1;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"collector-owned direct search handler accepted");
    sf_reset();sf_require(ps_physical_search_only() && ps_physical_owner==1 && ps_physical_ack==8 && sf_mock_count==1 && sf_mock_stops==1 && sf_mock_samples==1,"no-target transfer failed");
    sf_require(!ps_collect_count && load8(ps_nav_map)==17 && load8(ps_discovery_observed)==19 && load8(ps_collect_points)==23 && load8(ps_case_target)==29,"search-only transfer injected target or floor");
    sf_reset();ps_brick_count=1;sf_require(ps_physical_search_only() && ps_physical_owner==0 && ps_physical_ack==2 && !sf_mock_count,"new target incorrectly transferred search ownership");
    sf_reset();sf_mock_stop=0;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_samples && !sf_mock_count,"failed stop did not latch");
    sf_reset();sf_mock_camera=0;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"moving camera did not latch");
    sf_reset();ps_local_mode=0;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"oracle localization accepted");
    sf_reset();ps_agent_physical=0;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"nonphysical owner accepted");
    sf_reset();ps_agent_oracle=1;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"oracle labels accepted");
    sf_reset();ps_nav_training_oracle=1;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"training oracle accepted");
    sf_reset();ps_collect_enabled=0;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"disabled collector accepted");
    sf_reset();ps_discovery_enabled=0;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"disabled discovery accepted");
    sf_reset();ps_seek_enabled=1;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"incompatible controller accepted");
    sf_reset();sf_mock_rgb=0;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"failed RGB did not latch");
    sf_reset();sf_mock_detect=0;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"detector failure did not latch");
    sf_reset();sf_mock_stale=1;ps_brick_frame=99;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && !sf_mock_count,"stale no-target frame did not latch");
    sf_reset();sf_mock_collector=0;sf_require(!ps_physical_search_only() && ps_physical_owner==2 && sf_mock_count==1,"collector failure did not latch");
    sf_reset();sf_require(ps_physical_handoff() && ps_physical_owner==0 && ps_physical_ack==2 && !sf_mock_count,"normal no-target handoff changed");
    sf_reset();ps_brick_count=1;sf_require(ps_physical_handoff() && ps_physical_owner==1 && ps_physical_ack==3 && sf_mock_count==1,"normal target handoff changed");
    // The disposable loop starts after reset. Exercise the actual candidate
    // command-8 dispatch and subsequent command-3 branch with fake transport.
    sf_reset();sf_loop_requests=0;sf_loop_observations=0;ps_agent_fd=syscall(2,"/dev/null",2,0,0,0,0);
    sf_require(ps_agent_fd>=0 && !ps_physical_loop(0,0) && sf_loop_requests==2 && sf_loop_observations==2,"physical command dispatch failed");
    syscall(3,ps_agent_fd,0,0,0,0,0);
    pl_print(1,"Physical search-only CPU dispatch probe passed.\n");return 0;
}
