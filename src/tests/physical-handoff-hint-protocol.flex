// Appended to a test-only simulator source copy with sensor/actuator mocks.
fn ph_protocol_require(ok,message) { if !ok { pl_print(2,message);pl_print(2,"\n");syscall(231,1,0,0,0,0,0); } return 0; }
fn ph_protocol_setup() {
    ps_plant=alloc(2048);ps_bus=alloc(2048);pb_zero(ps_plant,2048);pb_zero(ps_bus,2048);store64(ps_plant+8,ps_bus);
    ps_brick_records=alloc(256);pb_zero(ps_brick_records,256);ps_brick_count=1;
    store64(ps_brick_records,10);store64(ps_brick_records+8,10);store64(ps_brick_records+16,30);store64(ps_brick_records+24,30);
    store64(ps_brick_records+32,ps_number(1,2));store64(ps_brick_records+64,1);
    ps_collect_enabled=1;ps_agent_physical=1;ps_physical_owner=0;ps_seek_enabled=0;ps_local_mode=2;ps_camera_drive_mode=1;
    ps_local_x=0;ps_local_y=0;ps_total=100;ps_brick_frame=100;ps_handoff_hint_enabled=1;ps_collect_reset();return 0;
}
fn main(argc,argv) {
    if !pl_init() { return 2; } ph_protocol_setup();
    ph_mock_stop=0;ph_protocol_require(!ps_physical_handoff() && ps_physical_owner==2 && !ps_handoff_hint_captures,"stop failure captured hint");
    ps_physical_owner=0;ph_mock_stop=1;ph_mock_rgb=0;ph_protocol_require(!ps_physical_handoff() && ps_physical_owner==2 && !ps_handoff_hint_captures,"RGB failure captured hint");
    ps_physical_owner=0;ph_mock_rgb=1;ph_mock_detect=0;ph_protocol_require(!ps_physical_handoff() && ps_physical_owner==2 && !ps_handoff_hint_captures,"detector failure captured hint");
    ps_physical_owner=0;ph_mock_detect=1;ps_brick_count=0;ph_protocol_require(ps_physical_handoff() && ps_physical_ack==2 && !ps_handoff_hint_captures,"empty frame accepted");
    ps_brick_count=1;ps_physical_owner=0;ph_mock_stale=1;ps_brick_frame=99;ph_protocol_require(ps_physical_handoff() && ps_physical_ack==2 && !ps_handoff_hint_captures,"stale frame accepted");
    ph_mock_stale=0;ps_physical_owner=0;ph_mock_collector=0;ph_protocol_require(!ps_physical_handoff() && ps_physical_owner==2 && !ps_handoff_hint_captures,"failed collector captured hint");
    ph_mock_collector=1;ps_physical_owner=0;ph_protocol_require(ps_physical_handoff() && ps_physical_owner==1 && ps_physical_ack==3,"valid handoff failed");
    ph_protocol_require(ps_handoff_hint_captures==1 && ps_handoff_hint_valid && !ps_collect_count,"valid handoff did not retain one unconfirmed hint");
    // Exercise the real ps_collect_observe dispatch with mocked rendering.
    ps_nav_map=alloc(32);ps_discovery_observed=alloc(32);store8(ps_nav_map,17);store8(ps_discovery_observed,19);
    ps_total=110;ps_brick_frame=110;pb_copy(ps_brick_records+128,ps_brick_records,128);ps_brick_count=2;
    ph_protocol_require(ps_collect_observe(),"collector did not hold for another observation");
    ph_protocol_require(ps_collect_count==1 && load64(ps_collect_points+32)==2 && ps_handoff_hint_uses==1,"collector did not merge hint exactly once");
    ph_protocol_require(load8(ps_nav_map)==17 && load8(ps_discovery_observed)==19,"hint changed floor evidence");
    ps_collect_observe();ph_protocol_require(load64(ps_collect_points+32)==2,"multiple same-frame candidates inflated confirmation");
    ps_total=120;ps_brick_frame=120;ps_collect_observe();ph_protocol_require(load64(ps_collect_points+32)==3,"third distinct collector frame not confirmed");
    ps_house_ready=0;ph_protocol_require(!ps_collect_select(),"collector bypassed home localization");
    ps_house_ready=1;ps_collect_map_until=1;ps_discovery_scans=0;ph_protocol_require(!ps_collect_select(),"collector bypassed unknown map");
    ps_collect_reset();ps_house_ready=0;ps_physical_owner=0;ps_total=200;ps_brick_frame=200;ps_brick_count=1;
    ph_protocol_require(ps_physical_handoff() && ps_handoff_hint_valid,"missing-frame setup handoff failed");
    ps_total=210;ps_brick_frame=210;ps_brick_count=0;ps_collect_observe();
    ph_protocol_require(!ps_handoff_hint_valid && !ps_collect_count && !ps_handoff_hint_uses,"empty collector frame did not discard hint");
    ps_collect_reset();ps_physical_owner=0;ps_total=300;ps_brick_frame=300;ps_brick_count=1;
    ph_protocol_require(ps_physical_handoff() && ps_handoff_hint_valid,"different-color setup handoff failed");
    ps_total=310;ps_brick_frame=310;store64(ps_brick_records+64,2);ps_collect_observe();
    ph_protocol_require(!ps_handoff_hint_valid && ps_collect_count==1 && load64(ps_collect_points+32)==1 && !ps_handoff_hint_uses,"different first collector observation credited hint");
    pl_print(1,"Physical handoff ordering CPU probe passed.\n");return 0;
}
