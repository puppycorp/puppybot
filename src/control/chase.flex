// Chase game: drive to a brick that reappears somewhere new after every reach.
// Placement uses the privileged floorplan. The teacher steers only from the
// camera's brick detection and its odometry memory of the last sighting.
// Fetch game: after each reach, stop facing the box before the next brick
// appears; a carrying bit in the last feedback slot says which leg is active.
import "workflow.flex";
import "actions.flex";
global vw_chase=0;
global vw_chase_forward=0;
global vw_fetch=0;
// Ablation: the policy always sees "not carrying".
global vw_hide_carry=0;
// Search-heavy fetch data: bricks start out of camera view, up to 2 m from the box.
global vw_far_bricks=0;
// Search-difficulty level of every fetch brick placement (0 keeps the normal placement).
global vw_level=0;
// Fetch teacher search with planned routes: 1 covers the floor the camera has not
// seen yet, 2 sweeps (a full turn, then away along an open direction in view).
global vw_explore=0;
// Analysis: run writes the policy's memory and true task facts at every step.
global vw_record_memory=0;
// Collection with --explore-teacher: map.bin holds the robot-centred coverage map of every row (vx_map_row).
global vw_record_map=0;
global vx_map_base=0;
// Collection: per-step percent chance of a burst of 2-6 actions of one random
// drive class in place of the driver's, labels unchanged (noise injection).
global vw_action_noise=0;
// Collection with --policy: label the student's own executed actions, kept only
// for bricks delivered within this many steps of appearing (self-imitation).
global vw_self_keep=0;
// Collection with --policy: the student samples its action from its softmax and
// each row's weight holds the discounted reward that followed it (reinforcement learning).
global vw_sample_actions=0;
global vw_straight_bias=0;
global vw_straight_after=0;
global vw_door_pass=0;
global vw_ensemble=0;
global vw_ensemble_count=0;
global vw_ensemble_until=0;
global vx_members=0;
global vx_member_hidden=0;
global vx_mean=0;
global vw_door_early=0;
global vx_pass=0;
global vx_pass_side=1;
global vx_pass_steps=0;
global vx_pass_last=0;
global vx_pass_door=0;
global vx_sample_rng=1;
global vx_rewards=0;
global vx_reward_place=-1;
global vx_reward_room=-1;
global vx_returns=0;
global vx_rng=1;
global vx_reaches=0;
global vx_jumps=0;
global vx_jump_step=-1;
global vx_brick=0;
global vx_target=0;
global vx_seen_step=-1000;
global vx_missing=0;
global vx_side=1;
global vx_escape=0;
// The class of the last action chosen, so a wall reverse can keep turning the same way.
global vx_last_class=-1;
global vx_contacts=0;
// Ping-pong: actions inside runs of at least six that flip drive direction every action and add up to at most one
// action's turn (a three-point turn keeps turning one way and does not count).
global vx_drive=0;
global vx_chain=0;
global vx_pingpong=0;
global vx_turns=0;
global vx_marked=-1;
// Back and forth: actions inside 20-action stretches (4 s) that end under 0.25 m and 45 degrees from where they began
// with at least four drive reversals, which also catches slower loops than ping-pong (three actions each way).
global vx_trail=0;
global vx_backforth=0;
global vx_backforth_marked=-1;
global vx_log=0;
global vx_disagree=0;
global vx_deliveries=0;
global vx_carrying=0;
global vx_home=0;
global vx_home_seen=0;
global vx_home_step=-1000;
global vx_lost=0;
global vx_stuck=0;
global vx_seen=0;
global vx_spot=0;
global vx_wall=0;
global vx_goal=-1;
global vx_misses=0;
global vx_sweep_phase=0;
global vx_sweep_turn=0;
global vx_sweep_heading=0;
global vx_sweep_fresh=1;
global vx_sweep_steps=0;
global vx_sweep_from=0;
global vx_sweep_back=0;
global vx_memory_fd=-1;
global vx_memory_row=0;
global vx_place_step=0;
global vx_search_carry=0;
global vx_search_from=0;
global vx_noise_rng=1;
global vx_noise_left=0;
global vx_noise_class=0;
global vx_noisy=0;
global vx_kept=0;
global vx_noise_marks=0;
global vx_memory_turn=0;
global vx_memory_heading=0;
global vx_memory_seen=-1;
fn vx_random() {vx_rng=(vx_rng*1103515245+12345)&2147483647;return vc_number(vx_rng,2147483648);}
fn vx_uniform(lo,hi) {return f64_add(lo,f64_mul(f64_sub(hi,lo),vx_random()));}
fn vx_sign() {if f64_lt(vx_random(),vc_number(1,2)) {return f64_from_i64(-1);}return PB_ONE;}
// Exploration grid on the oracle's 10 cm cells: routes keep 0.30 m from walls
// (a carried brick lengthens the robot), search goals keep the brick placement
// clearance, and walls or the box occlude the camera.
fn vx_grid() {
    vo_width=f64_to_i64_nearest(f64_mul(f64_sub(load64(vo_world+80),load64(vo_world+64)),f64_from_i64(10)));vo_height=f64_to_i64_nearest(f64_mul(f64_sub(load64(vo_world+88),load64(vo_world+72)),f64_from_i64(10)));
    vc_require(vo_width>=1 && vo_height>=1 && vo_width<=400 && vo_height<=400,"exploration floor bounds exceed 40 m");let cells=vo_width*vo_height;
    vo_grid=alloc(cells);vo_distance=alloc(cells*8);vo_queue=alloc(cells*8);vo_route=alloc(cells*16);if !vx_seen {vx_seen=alloc(160000);vx_spot=alloc(160000);vx_wall=alloc(160000);}
    let i=0;while i<cells {let x=vo_x(i%vo_width);let y=vo_y(i/vo_width);vo_clearance=vc_number(30,100);store8(vo_grid+i,vo_free(x,y));store8(vx_spot+i,load8(vo_grid+i));vo_clearance=vc_number(4,100);store8(vx_wall+i,!vo_free(x,y));i=i+1;}
    return 0;
}
// Floor and box clearance only; unlike vo_open this plans no route to the case brick.
fn vx_world(directory) {
    vo_close();let old=pj_arena;let used=pj_used;pj_arena=alloc(131072);let root=vc_json_file(vc_path(vc_path(directory,"scene"),"case.json"));
    let box=pj_get(root,"container");let position=pj_get(box,"position");let size=pj_get(box,"innerSize");let wall=pj_real_node(pj_get(box,"wallThickness"));if !vo_box {vo_box=alloc(32);}
    store64(vo_box,pj_real_node(pj_index(position,0)));store64(vo_box+8,pj_real_node(pj_index(position,1)));store64(vo_box+16,f64_add(f64_mul(pj_real_node(pj_index(size,0)),vc_number(1,2)),wall));store64(vo_box+24,f64_add(f64_mul(pj_real_node(pj_index(size,1)),vc_number(1,2)),wall));vc_require(!pj_error,"invalid chase box reference");
    syscall(11,pj_arena,131072,0,0,0,0);pj_arena=old;pj_used=used;vo_world=vc_map(vc_path(vc_path(directory,"scene"),"environment.bin"));vo_world_size=vc_size;
    vc_require(vo_world_size>=256 && load64(vo_world)==load64("PBENV001") && load64(vo_world+8)>=0 && load64(vo_world+8)<=128 && vo_world_size>=256+load64(vo_world+8)*128,"invalid chase environment");vo_width=0;vo_height=0;if vw_explore {vx_grid();}return 0;
}
fn vx_note(reason,x,y) {
    let text=alloc(512);let b=alloc(32);pl_builder(b,text,512);pl_text(b,"{\"step\":");pl_int(b,ve_steps);pl_text(b,",\"event\":");pj_text(b,reason);pl_text(b,",\"brick\":[");pl_float(b,x);pl_char(b,44);pl_float(b,y);
    pl_text(b,"],\"robot\":[");pl_float(b,load64(ve_pose));pl_char(b,44);pl_float(b,load64(ve_pose+8));pl_char(b,44);pl_float(b,load64(ve_pose+16));pl_text(b,"]}\n");
    vc_require(!load64(b+24) && !pl_write(vx_log,text,load64(b+8)),"cannot journal chase placement");syscall(11,text,512,0,0,0,0);syscall(11,b,32,0,0,0,0);
    vx_place_step=ve_steps;vx_memory_turn=0;vx_memory_heading=load64(ve_pose+16);vx_memory_seen=-1;return 0;
}
fn vx_send(x,y,yaw) {
    ve_sequence=ve_sequence+1;pb_zero(ve_request,64);store64(ve_request,5);store64(ve_request+8,ve_sequence);store64(ve_request+24,x);store64(ve_request+32,y);store64(ve_request+40,yaw);
    vc_io(0,load64(ve_process+8),ve_request,64);ve_receive();
    vc_require(vc_json_int(ve_state,"findReturn","consumedIndex")<0,"chase placement did not restore the brick");
    vc_require(vc_json_int(pj_get(ve_state,"case"),"perception","frameId")==vc_json_int(ve_state,"totalSteps",0),"camera frame is stale after placement");return 0;
}
// Mostly in view, some beside the robot, a few behind it; always reachable in a straight line when possible.
fn vx_place(reason) {
    let x=load64(ve_pose);let y=load64(ve_pose+8);let h=load64(ve_pose+16);let px=0;let py=0;let ok=0;let tries=0;vo_clearance=vc_number(30,100);
    while !ok && tries<600 {
        let u=vx_random();let bearing=vx_uniform(vc_number(-45,100),vc_number(45,100));let distance=vx_uniform(vc_number(6,10),vc_number(22,10));
        if f64_ge(u,vc_number(6,10)) {bearing=f64_mul(vx_sign(),vx_uniform(vc_number(6,10),vc_number(15,10)));distance=vx_uniform(vc_number(6,10),vc_number(16,10));}
        if f64_ge(u,vc_number(9,10)) {bearing=f64_mul(vx_sign(),vx_uniform(vc_number(15,10),pb_radians(f64_from_i64(180))));distance=vx_uniform(vc_number(6,10),vc_number(15,10));}
        if tries>=400 {bearing=vx_uniform(pb_neg(pb_radians(f64_from_i64(180))),pb_radians(f64_from_i64(180)));distance=vx_uniform(vc_number(6,10),f64_from_i64(3));}
        px=f64_add(x,f64_mul(distance,f64_cos(f64_add(h,bearing))));py=f64_add(y,f64_mul(distance,f64_sin(f64_add(h,bearing))));
        vo_clearance=vc_number(30,100);ok=vo_free(px,py);if ok && tries<200 {vo_clearance=vc_number(20,100);ok=vo_line(f64_add(x,f64_mul(vc_number(3,10),f64_cos(f64_add(h,bearing)))),f64_add(y,f64_mul(vc_number(3,10),f64_sin(f64_add(h,bearing)))),px,py);}tries=tries+1;
    }
    vc_require(ok,"no free chase placement");store64(vx_brick,px);store64(vx_brick+8,py);vx_send(px,py,vx_uniform(0,pb_radians(f64_from_i64(180))));vx_note(reason,px,py);
    // A fifth of fresh targets later jump once while the robot is still on its way.
    vx_jump_step=-1;if !pl_equal(reason,"jump") && f64_lt(vx_random(),vc_number(2,10)) {vx_jump_step=ve_steps+4+f64_to_i64_nearest(f64_mul(vx_random(),f64_from_i64(8)));}
    if !pl_equal(reason,"jump") {vx_seen_step=-1000;vx_missing=0;}return 0;
}
// Two-room layouts split at a vertical partition wall with a doorway; room 1 lies east of it.
fn vx_partition() {let i=0;while i<load64(vo_world+8) {let r=vo_world+256+i*128;if pl_starts(r,"Wall.partition") {return r;}i=i+1;}return 0;}
fn vx_room(x) {let wall=vx_partition();if wall && f64_gt(x,load64(wall+48)) {return 1;}return 0;}
// Doorway centre: the gap between the top of the lower partition wall and the bottom of the upper one.
fn vx_doorway(out) {
    let low=0;let high=0;let i=0;
    while i<load64(vo_world+8) {let r=vo_world+256+i*128;if pl_starts(r,"Wall.partition") {if !low || f64_lt(load64(r+56),load64(low+56)) {low=r;}if !high || f64_gt(load64(r+56),load64(high+56)) {high=r;}}i=i+1;}
    vc_require(low && high && low!=high,"doorway needs two partition walls");
    store64(out,load64(low+48));store64(out+8,f64_mul(f64_add(f64_add(load64(low+56),load64(low+80)),f64_sub(load64(high+56),load64(high+80))),vc_number(1,2)));return 0;
}
// A new brick is unseen everywhere, and a sweep starts with a full turn.
fn vx_forget() {if vx_seen {pb_zero(vx_seen,vo_width*vo_height);}vx_goal=-1;vx_pass=0;vx_sweep_phase=0;vx_sweep_turn=0;vx_sweep_fresh=1;vx_sweep_back=0;return 0;}
// Result name of a level's placement, so games from before the 4/5 swap can be told apart.
fn vx_level_name(b) {
    if vw_level==1 {return pj_text(b,"in view");}if vw_level==2 {return pj_text(b,"just off view");}if vw_level==3 {return pj_text(b,"same room out of view");}
    if vw_level==4 {return pj_text(b,"doorway drill");}return pj_text(b,"other room");
}
// Levels place each brick relative to the robot's pose at placement time:
// 1 in view (0.6-1.5 m, within 35 degrees of the heading, inside the camera's
// 37.6 degree half-angle); 2 just off view (0.6-1.5 m, 40-90 degrees); 3 out of
// view in the same room (1.0-2.5 m behind, or 1.8-3.0 m in any direction, past the
// camera's range); 4, a doorway drill on a two-room layout, half level 1 and half
// 0.6-1.5 m past the doorway in the other room (within 0.8 m of its centre line);
// 5 anywhere free in the other room of a two-room layout. Before 2 Nov 2026 4 and
// 5 were the other way round. Levels 1-2 keep a clear straight line from the robot when possible. A fetch
// robot faces the box at every placement, which can block the whole level 1 cone,
// so that cone widens by 10 degrees every 300 tries.
fn vx_place_level(reason) {
    let x=load64(ve_pose);let y=load64(ve_pose+8);let h=load64(ve_pose+16);let room=vx_room(x);let px=0;let py=0;let ok=0;let tries=0;
    vc_require(vw_level<4 || vx_partition(),"levels 4 and 5 need a two-room layout");
    let mode=vw_level;let door=alloc(16);if vw_level==4 {vx_doorway(door);mode=1;if f64_lt(vx_random(),vc_number(1,2)) {mode=4;}}
    while !ok && tries<2000 {
        if mode==4 {let side=PB_ONE;if room {side=f64_from_i64(-1);}px=f64_add(load64(door),f64_mul(side,vx_uniform(vc_number(6,10),vc_number(15,10))));py=f64_add(load64(door+8),vx_uniform(vc_number(-8,10),vc_number(8,10)));}
        else if mode==5 {px=vx_uniform(load64(vo_world+64),load64(vo_world+80));py=vx_uniform(load64(vo_world+72),load64(vo_world+88));}
        else {let range=vx_uniform(vc_number(6,10),vc_number(15,10));let wide=pb_radians(f64_from_i64(35+10*(tries/300)));let bearing=vx_uniform(pb_neg(wide),wide);
            if mode==2 {bearing=f64_mul(vx_sign(),vx_uniform(pb_radians(f64_from_i64(40)),pb_radians(f64_from_i64(90))));}
            if mode==3 {if f64_lt(vx_random(),vc_number(1,2)) {range=vx_uniform(PB_ONE,vc_number(25,10));bearing=f64_mul(vx_sign(),vx_uniform(pb_radians(f64_from_i64(90)),pb_radians(f64_from_i64(180))));}
                else {range=vx_uniform(vc_number(18,10),f64_from_i64(3));bearing=vx_uniform(pb_neg(pb_radians(f64_from_i64(180))),pb_radians(f64_from_i64(180)));}}
            px=f64_add(x,f64_mul(range,f64_cos(f64_add(h,bearing))));py=f64_add(y,f64_mul(range,f64_sin(f64_add(h,bearing))));}
        vo_clearance=vc_number(30,100);ok=vo_free(px,py);
        if ok {if mode>=4 {ok=vx_room(px)!=room;}else {ok=vx_room(px)==room;}}
        if ok && mode<=2 && tries<1500 {vo_clearance=vc_number(20,100);let rx=f64_sub(px,x);let ry=f64_sub(py,y);let range=f64_hypot(rx,ry);ok=vo_line(f64_add(x,f64_mul(vc_number(3,10),f64_div(rx,range))),f64_add(y,f64_mul(vc_number(3,10),f64_div(ry,range))),px,py);}
        tries=tries+1;
    }
    vc_require(ok,"no free level placement");store64(vx_brick,px);store64(vx_brick+8,py);vx_send(px,py,vx_uniform(0,pb_radians(f64_from_i64(180))));vx_note(reason,px,py);
    syscall(11,door,16,0,0,0,0);vx_jump_step=-1;vx_seen_step=-1000;vx_missing=0;vx_forget();return 0;
}
// Fetch bricks lie 0.7-1.5 m from the box, so the box is near after every reach,
// and in a straight line from the robot that does not cross the box when possible.
// With --far-bricks they lie 0.7-2.0 m from the box and out of camera view: more
// than 1.8 m away or more than 35 degrees off the heading (the first 500 tries).
fn vx_place_fetch(reason) {
    if vw_level {return vx_place_level(reason);}
    let cx=load64(vo_box);let cy=load64(vo_box+8);let px=0;let py=0;let ok=0;let tries=0;let farthest=vc_number(15,10);if vw_far_bricks {farthest=f64_from_i64(2);}
    while !ok && tries<600 {
        let angle=vx_uniform(pb_neg(pb_radians(f64_from_i64(180))),pb_radians(f64_from_i64(180)));let distance=vx_uniform(vc_number(7,10),farthest);
        px=f64_add(cx,f64_mul(distance,f64_cos(angle)));py=f64_add(cy,f64_mul(distance,f64_sin(angle)));vo_clearance=vc_number(30,100);
        let rx=f64_sub(px,load64(ve_pose));let ry=f64_sub(py,load64(ve_pose+8));let range=f64_hypot(rx,ry);ok=vo_free(px,py) && f64_gt(range,vc_number(6,10));
        if ok && vw_far_bricks && tries<500 {let off=f64_magnitude(pb_wrap_pi(f64_sub(f64_atan2(ry,rx),load64(ve_pose+16))));ok=f64_gt(range,vc_number(18,10)) || f64_gt(off,pb_radians(f64_from_i64(35)));}
        if ok && tries<400 {vo_clearance=vc_number(20,100);ok=vo_line(f64_add(load64(ve_pose),f64_mul(vc_number(3,10),f64_div(rx,range))),f64_add(load64(ve_pose+8),f64_mul(vc_number(3,10),f64_div(ry,range))),px,py);}tries=tries+1;
    }
    vc_require(ok,"no free fetch placement");store64(vx_brick,px);store64(vx_brick+8,py);vx_send(px,py,vx_uniform(0,pb_radians(f64_from_i64(180))));vx_note(reason,px,py);
    vx_jump_step=-1;vx_seen_step=-1000;vx_missing=0;vx_forget();return 0;
}
fn vx_set(action,class) {pb_put32(action,ca_steering_bits(class));pb_put32(action+4,ca_speed_bits(class));vx_last_class=class;return class;}
// Fetch searches drive straight for 12 actions after each full circle, so a
// target out of camera range is eventually approached.
fn vx_search(action) {
    let h=load64(ve_pose+16);vo_clearance=vc_number(22,100);vx_lost=vx_lost+1;
    if !vo_free(f64_add(load64(ve_pose),f64_mul(vc_number(3,10),f64_cos(h))),f64_add(load64(ve_pose+8),f64_mul(vc_number(3,10),f64_sin(h)))) {vx_escape=1;if vx_side>0 {return vx_set(action,5);}return vx_set(action,3);}
    if vw_fetch && vx_lost%48>=36 {return vx_set(action,1);}
    if vx_side>0 {return vx_set(action,0);}return vx_set(action,2);
}
// A fetch robot pinned by contact alternates forward and reverse every four actions.
fn vx_unstick(action) {
    if !ve_contact {vx_stuck=0;return -1;}vx_stuck=vx_stuck+1;if !vw_fetch || vx_stuck<3 {return -1;}
    vx_escape=0;if (vx_stuck/4)%2 {return vx_set(action,1);}return vx_set(action,4);
}
// Contact recovery shared by both legs; -1 when the robot is free to drive.
fn vx_recover(action) {
    let unstick=vx_unstick(action);if unstick>=0 {return unstick;}
    if vx_escape>0 {vx_escape=vx_escape-1;if vx_side>0 {return vx_set(action,5);}return vx_set(action,3);}
    if ve_contact {vx_escape=2;return vx_set(action,4);}return -1;
}
// Camera coverage from the true pose: rays 27.5 degrees either side of the heading
// out to 1.9 m (inside the 37.6 degree half-angle, less a cell, and the 2 m detection range),
// stopped by walls and the box; the 0.35 m reach around the robot counts too.
fn vx_look() {
    let x=load64(ve_pose);let y=load64(ve_pose+8);let h=load64(ve_pose+16);let ray=-11;
    while ray<=14 {let angle=f64_add(h,pb_radians(vc_number(ray*5,2)));let c=f64_cos(angle);let s=f64_sin(angle);let step=1;let open=1;
        while open && step<=38 {let cell=vo_cell(f64_add(x,f64_mul(vc_number(step*5,100),c)),f64_add(y,f64_mul(vc_number(step*5,100),s)));if cell<0 || load8(vx_wall+cell) {open=0;}else {store8(vx_seen+cell,1);}step=step+1;}ray=ray+1;
    }
    let dy=-4;while dy<=4 {let dx=-4;while dx<=4 {let cell=vo_cell(f64_add(x,vc_number(dx,10)),f64_add(y,vc_number(dy,10)));if cell>=0 && dx*dx+dy*dy<=12 {store8(vx_seen+cell,1);}dx=dx+1;}dy=dy+1;}return 0;
}
// Coverage map of 12x12 cells of 40 cm around the true pose, row 0 farthest ahead and column 0 leftmost:
// 1 when most of the floor that could hold a brick there is covered, 0 when not, 2 when there is none.
fn vx_map_row(out) {
    let x=load64(ve_pose);let y=load64(ve_pose+8);let c=f64_cos(load64(ve_pose+16));let s=f64_sin(load64(ve_pose+16));let row=0;
    while row<12 {let col=0;while col<12 {let spots=0;let seen=0;let i=0;
            while i<16 {let ahead=vc_number(240-row*40-(i/4)*10-5,100);let left=vc_number(240-col*40-(i%4)*10-5,100);
                let cell=vo_cell(f64_sub(f64_add(x,f64_mul(ahead,c)),f64_mul(left,s)),f64_add(f64_add(y,f64_mul(ahead,s)),f64_mul(left,c)));
                if cell>=0 && load8(vx_spot+cell) {spots=spots+1;if load8(vx_seen+cell) {seen=seen+1;}}i=i+1;}
            let label=2;if spots {label=seen*2>=spots;}store8(out+row*12+col,label);col=col+1;}row=row+1;}
    return out;
}
// Breadth-first route distances from the robot's cell; the first four hops may
// cross cells without route clearance so a robot beside a wall can leave it.
fn vx_bfs(start) {
    let cells=vo_width*vo_height;let i=0;while i<cells {store64(vo_distance+i*8,-1);i=i+1;}store64(vo_distance+start*8,0);store64(vo_queue,start);let head=0;let tail=1;
    while head<tail {
        let cell=load64(vo_queue+head*8);head=head+1;let hop=load64(vo_distance+cell*8);let k=0;
        while k<4 {let next=cell-vo_width;if k==1 {next=cell+vo_width;}if k==2 {next=cell-1;}if k==3 {next=cell+1;}
            if next>=0 && next<cells && (k<2 || next/vo_width==cell/vo_width) && (load8(vo_grid+next) || hop<4) && load64(vo_distance+next*8)<0 {store64(vo_distance+next*8,hop+1);store64(vo_queue+tail*8,next);tail=tail+1;}k=k+1;
        }
    }
    return tail;
}
// Drive toward a true-frame point, turning by reversing when it lies far to one side.
fn vx_aim(action,tx,ty) {
    let error=pb_wrap_pi(f64_sub(f64_atan2(f64_sub(ty,load64(ve_pose+8)),f64_sub(tx,load64(ve_pose))),load64(ve_pose+16)));if f64_gt(error,0) {vx_side=1;}else {vx_side=-1;}
    if f64_gt(f64_magnitude(error),vc_number(13,10)) {if vx_side>0 {return vx_set(action,5);}return vx_set(action,3);}
    if f64_gt(error,vc_number(2,10)) {return vx_set(action,0);}if f64_lt(error,vc_number(-2,10)) {return vx_set(action,2);}return vx_set(action,1);
}
// Follow the latest BFS route to goal: aim at the farthest route cell within
// 0.45 m in a clear line. With a wall just ahead, back away turning toward it
// for three actions: after one the floor ahead looks open again, and driving
// on undoes the turn, so a one-action reverse rocks in place. Right after a
// forward turn the reverse keeps the nose turning the same way, as in a
// three-point turn: at a wall corner the aim swaps sides, and turning toward
// it there undoes the forward turn every time.
fn vx_route(action,goal) {
    let count=0;let cell=goal;
    while load64(vo_distance+cell*8)>0 {store64(vo_route+count*8,cell);count=count+1;let k=0;let best=cell;
        while k<4 {let next=cell-vo_width;if k==1 {next=cell+vo_width;}if k==2 {next=cell-1;}if k==3 {next=cell+1;}
            if next>=0 && next<vo_width*vo_height && (k<2 || next/vo_width==cell/vo_width) && load64(vo_distance+next*8)>=0 && load64(vo_distance+next*8)<load64(vo_distance+best*8) {best=next;}k=k+1;
        }cell=best;
    }
    let x=load64(ve_pose);let y=load64(ve_pose+8);let aim=goal;
    if count {aim=load64(vo_route+(count-1)*8);let i=count-2;let stopped=0;vo_clearance=vc_number(26,100);
        while i>=0 && !stopped {let next=load64(vo_route+i*8);let px=vo_x(next%vo_width);let py=vo_y(next/vo_width);if f64_gt(f64_hypot(f64_sub(px,x),f64_sub(py,y)),vc_number(45,100)) || !vo_line(x,y,px,py) {stopped=1;}else {aim=next;}i=i-1;}
    }
    let h=load64(ve_pose+16);vo_clearance=vc_number(22,100);
    if !vo_free(f64_add(x,f64_mul(vc_number(3,10),f64_cos(h))),f64_add(y,f64_mul(vc_number(3,10),f64_sin(h)))) {
        vx_escape=2;if vx_last_class==2 {vx_side=-1;return vx_set(action,3);}if vx_last_class==0 {vx_side=1;return vx_set(action,5);}
        if f64_gt(pb_wrap_pi(f64_sub(f64_atan2(f64_sub(vo_y(aim/vo_width),y),f64_sub(vo_x(aim%vo_width),x)),h)),0) {vx_side=1;return vx_set(action,5);}vx_side=-1;return vx_set(action,3);
    }
    return vx_aim(action,vo_x(aim%vo_width),vo_y(aim/vo_width));
}
// Unseen cells that could hold a brick in the 5x5 cells around cell.
fn vx_gain(cell) {
    let row=cell/vo_width;let col=cell%vo_width;let count=0;let dy=-2;
    while dy<=2 {let dx=-2;while dx<=2 {let r=row+dy;let c=col+dx;if r>=0 && c>=0 && r<vo_height && c<vo_width && load8(vx_spot+r*vo_width+c) && !load8(vx_seen+r*vo_width+c) {count=count+1;}dx=dx+1;}dy=dy+1;}return count;
}
// Search goal: keep the current unseen cell, else score unseen cells that could
// hold a brick up to 1.5 m of route beyond the nearest one: route cells, plus 3
// per radian of turn, minus half the unseen cells around it. With every
// reachable cell covered, start the cover again.
fn vx_explore(action) {
    let start=vo_cell(load64(ve_pose),load64(ve_pose+8));if start<0 {return vx_search(action);}let reached=vx_bfs(start);
    if vx_goal<0 || load8(vx_seen+vx_goal) || load64(vo_distance+vx_goal*8)<0 {
        vx_goal=-1;let best=0;let limit=-1;let i=0;let x=load64(ve_pose);let y=load64(ve_pose+8);let h=load64(ve_pose+16);
        while i<reached {let cell=load64(vo_queue+i*8);let hop=load64(vo_distance+cell*8);if limit>=0 && hop>limit {i=reached;}
            else {if load8(vx_spot+cell) && !load8(vx_seen+cell) {if limit<0 {limit=hop+15;}
                let turn=f64_magnitude(pb_wrap_pi(f64_sub(f64_atan2(f64_sub(vo_y(cell/vo_width),y),f64_sub(vo_x(cell%vo_width),x)),h)));
                let score=f64_sub(f64_add(f64_from_i64(hop),f64_mul(f64_from_i64(3),turn)),vc_number(vx_gain(cell),2));if vx_goal<0 || f64_lt(score,best) {vx_goal=cell;best=score;}}i=i+1;}
        }
    }
    if vx_goal<0 {vx_forget();return vx_search(action);}vx_lost=vx_lost+1;return vx_route(action,vx_goal);
}
// The box never moves and the robot starts beside it, so a carrying explorer
// routes to the box whenever it is out of mind or out of straight reach. Near
// an unseen box it faces the box, then backs away until the camera finds it.
fn vx_home_route(action) {
    let cx=load64(vo_box);let cy=load64(vo_box+8);let x=load64(ve_pose);let y=load64(ve_pose+8);let dx=f64_sub(cx,x);let dy=f64_sub(cy,y);let range=f64_hypot(dx,dy);
    vo_clearance=vc_number(24,100);if vx_home_seen && (f64_lt(range,vc_number(8,10)) || vo_line(x,y,f64_sub(cx,f64_mul(vc_number(6,10),f64_div(dx,range))),f64_sub(cy,f64_mul(vc_number(6,10),f64_div(dy,range))))) {return -1;}
    if f64_lt(range,vc_number(8,10)) {let recover=vx_recover(action);if recover>=0 {return recover;}
        if f64_lt(f64_magnitude(pb_wrap_pi(f64_sub(f64_atan2(dy,dx),load64(ve_pose+16)))),vc_number(25,100)) {return vx_set(action,4);}return vx_aim(action,cx,cy);}
    let start=vo_cell(x,y);if start<0 {return -1;}let reached=vx_bfs(start);let goal=-1;let i=0;
    while i<reached && goal<0 {let cell=load64(vo_queue+i*8);if f64_le(f64_hypot(f64_sub(vo_x(cell%vo_width),cx),f64_sub(vo_y(cell/vo_width),cy)),vc_number(8,10)) {goal=cell;}i=i+1;}
    if goal<0 {return -1;}let recover=vx_recover(action);if recover>=0 {return recover;}return vx_route(action,goal);
}
// Open floor straight ahead along heading h, in route cells from 0.3 m out, up to limit.
fn vx_open(h,limit) {
    let x=load64(ve_pose);let y=load64(ve_pose+8);let c=f64_cos(h);let s=f64_sin(h);let k=3;
    while k<=limit {let cell=vo_cell(f64_add(x,f64_mul(vc_number(k,10),c)),f64_add(y,f64_mul(vc_number(k,10),s)));if cell<0 || !load8(vo_grid+cell) {return k-1;}k=k+1;}return limit;
}
// Sweep search, decided from the current view and a short memory: turn a full
// circle, then keep turning until the heading shows a doorway into another room
// (1.5 m open) or 2 m of open floor (1.2 m after a second turn), never back the
// way the last drive came. Then route up to 2.5 m that way and turn again.
// Leaving through a doorway before the full circle loses 0.1-0.9 deliveries per
// minute on levels 1-4: nearby bricks not yet in view are abandoned. The floorplan only plans routes and measures what
// is open in view.
// --door-pass: once the heading shows a doorway, steer at a point 0.45 m short
// of its centre and then at one 0.6 m past it with the brick-approach steering
// law instead of the grid route, then turn a fresh circle in the new room.
fn vx_pass_drive(action) {
    let x=load64(ve_pose);let y=load64(ve_pose+8);let h=load64(ve_pose+16);
    if !vx_pass_door {vx_pass_door=alloc(16);}vx_doorway(vx_pass_door);let wall=load64(vx_pass_door);
    let p=f64_mul(f64_from_i64(vx_pass_side),f64_sub(x,wall));if vx_pass==1 && f64_ge(p,vc_number(-45,100)) {vx_pass=2;}
    let tx=f64_add(wall,f64_mul(f64_from_i64(vx_pass_side),vc_number(6,10)));if vx_pass==1 {tx=f64_sub(wall,f64_mul(f64_from_i64(vx_pass_side),vc_number(45,100)));}
    vo_clearance=vc_number(22,100);
    let ahead=vo_free(f64_add(x,f64_mul(vc_number(3,10),f64_cos(h))),f64_add(y,f64_mul(vc_number(3,10),f64_sin(h))));
    if ve_steps!=vx_pass_last+1 || vx_pass_steps>=80 || f64_ge(p,vc_number(6,10)) || !ahead {vx_pass=0;vx_sweep_phase=0;vx_sweep_turn=0;vx_sweep_fresh=1;return -1;}
    vx_pass_last=ve_steps;vx_pass_steps=vx_pass_steps+1;
    let error=pb_wrap_pi(f64_sub(f64_atan2(f64_sub(load64(vx_pass_door+8),y),f64_sub(tx,x)),h));
    if f64_gt(error,vc_number(2,10)) {return vx_set(action,0);}if f64_lt(error,vc_number(-2,10)) {return vx_set(action,2);}return vx_set(action,1);
}
fn vx_sweep(action) {
    let x=load64(ve_pose);let y=load64(ve_pose+8);let h=load64(ve_pose+16);vx_lost=vx_lost+1;
    if vx_pass {let pass=vx_pass_drive(action);if pass>=0 {return pass;}}
    if vx_sweep_phase {
        let start=vo_cell(x,y);
        if start>=0 && vx_goal>=0 && vx_sweep_steps<50 && f64_gt(f64_hypot(f64_sub(vo_x(vx_goal%vo_width),x),f64_sub(vo_y(vx_goal/vo_width),y)),vc_number(3,10)) {vx_bfs(start);if load64(vo_distance+vx_goal*8)>=0 {vx_sweep_steps=vx_sweep_steps+1;return vx_route(action,vx_goal);}}
        vx_sweep_phase=0;vx_sweep_turn=0;vx_sweep_fresh=1;
    }
    if vx_sweep_fresh {vx_sweep_heading=h;vx_sweep_fresh=0;}
    vx_sweep_turn=f64_add(vx_sweep_turn,f64_magnitude(pb_wrap_pi(f64_sub(h,vx_sweep_heading))));vx_sweep_heading=h;
    let circle=f64_mul(f64_from_i64(2),pb_radians(f64_from_i64(180)));
    // --door-early takes a doorway in view during the first circle too.
    if f64_ge(vx_sweep_turn,circle) || vw_door_early {
        let open=vx_open(h,30);let reach=vc_number(open,10);
        let ex=f64_add(x,f64_mul(reach,f64_cos(h)));let ey=f64_add(y,f64_mul(reach,f64_sin(h)));
        let away=!vx_sweep_back || f64_gt(f64_magnitude(pb_wrap_pi(f64_sub(h,f64_add(vx_sweep_from,pb_radians(f64_from_i64(180)))))),pb_radians(f64_from_i64(60))) || f64_ge(vx_sweep_turn,f64_mul(f64_from_i64(3),circle));
        let door=open>=15 && vx_room(ex)!=vx_room(x);
        let wide=open>=20 || (open>=12 && f64_ge(vx_sweep_turn,f64_mul(f64_from_i64(2),circle)));
        if vw_door_pass && away && door {
            vx_pass=1;vx_pass_side=1;if !vx_pass_door {vx_pass_door=alloc(16);}vx_doorway(vx_pass_door);if f64_gt(x,load64(vx_pass_door)) {vx_pass_side=-1;}
            vx_pass_steps=0;vx_pass_last=ve_steps-1;vx_sweep_from=h;vx_sweep_back=1;let pass=vx_pass_drive(action);if pass>=0 {return pass;}
        }
        if away && (door || wide) && f64_ge(vx_sweep_turn,circle) {
            let go=pb_min(open-4,25);let goal=vo_cell(f64_add(x,f64_mul(vc_number(go,10),f64_cos(h))),f64_add(y,f64_mul(vc_number(go,10),f64_sin(h))));
            let start=vo_cell(x,y);
            if go>=4 && goal>=0 && start>=0 && load8(vo_grid+goal) {vx_bfs(start);if load64(vo_distance+goal*8)>=0 {vx_goal=goal;vx_sweep_phase=1;vx_sweep_steps=1;vx_sweep_from=h;vx_sweep_back=1;return vx_route(action,goal);}}
        }
    }
    vo_clearance=vc_number(22,100);
    if !vo_free(f64_add(x,f64_mul(vc_number(3,10),f64_cos(h))),f64_add(y,f64_mul(vc_number(3,10),f64_sin(h)))) {if vx_side>0 {return vx_set(action,5);}return vx_set(action,3);}
    if vx_side>0 {return vx_set(action,0);}return vx_set(action,2);
}
// Exact seven-class labels: steer at the remembered camera sighting, reverse
// out of contacts, otherwise circle toward the side the brick was last seen.
// Before any sighting the search turns left, so every label follows from the
// camera history; mirror augmentation supplies the right-hand version.
// A seen brick with walls or the box in the straight line to it (one in the other
// room, seen through the doorway) is reached by route like unseen floor; driving
// straight at it bumps and backs off forever. The line is checked from 0.3 m out
// to 0.3 m short, since a robot beside the box has no clearance where it stands.
// -1 when the line is clear or the brick is within 0.8 m.
fn vx_brick_route(action) {
    let x=load64(ve_pose);let y=load64(ve_pose+8);let bx=load64(vx_brick);let by=load64(vx_brick+8);let dx=f64_sub(bx,x);let dy=f64_sub(by,y);let range=f64_hypot(dx,dy);
    vo_clearance=vc_number(20,100);let ux=f64_mul(vc_number(3,10),f64_div(dx,range));let uy=f64_mul(vc_number(3,10),f64_div(dy,range));
    if f64_lt(range,vc_number(8,10)) || vo_line(f64_add(x,ux),f64_add(y,uy),f64_sub(bx,ux),f64_sub(by,uy)) {return -1;}
    let start=vo_cell(x,y);if start<0 {return -1;}let reached=vx_bfs(start);let goal=-1;let i=0;
    while i<reached && goal<0 {let cell=load64(vo_queue+i*8);if f64_le(f64_hypot(f64_sub(vo_x(cell%vo_width),bx),f64_sub(vo_y(cell/vo_width),by)),vc_number(35,100)) {goal=cell;}i=i+1;}
    if goal<0 {return -1;}return vx_route(action,goal);
}
fn vx_teacher(action) {
    let local=pj_get(pj_get(ve_state,"localization"),"pose");vc_require(pj_kind(local)==3 && pj_count(local)==3,"invalid chase localization");
    let lx=pj_real_node(pj_index(local,0));let ly=pj_real_node(pj_index(local,1));let lh=pj_real_node(pj_index(local,2));
    let detections=pj_get(pj_get(pj_get(ve_state,"case"),"perception"),"detections");let seen=0;
    if pj_kind(detections)==3 && pj_count(detections) {let point=pj_get(pj_index(detections,0),"targetM");let tx=pj_real_node(pj_index(point,0));let ty=pj_real_node(pj_index(point,1));
        if !pj_error && f64_is_finite(tx) && f64_is_finite(ty) && f64_lt(f64_hypot(f64_sub(tx,lx),f64_sub(ty,ly)),vc_number(35,10)) {store64(vx_target,tx);store64(vx_target+8,ty);vx_seen_step=ve_steps;vx_missing=0;seen=1;}}
    vc_require(!pj_error,"invalid chase detection");if seen {vx_lost=0;vx_sweep_phase=0;vx_sweep_turn=0;vx_sweep_fresh=1;}
    // Audit only: the brick's cell became covered without a camera detection.
    if vw_explore==1 {let cell=vo_cell(load64(vx_brick),load64(vx_brick+8));let before=cell<0 || load8(vx_seen+cell);vx_look();if !before && load8(vx_seen+cell) && !seen && ve_steps-vx_seen_step>25 {vx_misses=vx_misses+1;}}
    let recover=vx_recover(action);if recover>=0 {return recover;}
    if ve_steps-vx_seen_step<=25 {
        let dx=f64_sub(load64(vx_target),lx);let dy=f64_sub(load64(vx_target+8),ly);let distance=f64_hypot(dx,dy);let error=pb_wrap_pi(f64_sub(f64_atan2(dy,dx),lh));
        if f64_gt(error,0) {vx_side=1;}else {vx_side=-1;}
        // A remembered brick that should be in view but is not was moved.
        if !seen && f64_lt(f64_magnitude(error),vc_number(3,10)) && f64_gt(distance,vc_number(5,10)) && f64_lt(distance,f64_from_i64(2)) {vx_missing=vx_missing+1;if vx_missing>=3 {vx_seen_step=-1000;}}
        if vx_seen_step>=0 {
            if vw_explore {let routed=vx_brick_route(action);if routed>=0 {return routed;}}
            if f64_gt(f64_magnitude(error),vc_number(13,10)) && f64_lt(distance,vc_number(7,10)) {if vx_side>0 {return vx_set(action,5);}return vx_set(action,3);}
            if f64_gt(error,vc_number(2,10)) {return vx_set(action,0);}if f64_lt(error,vc_number(-2,10)) {return vx_set(action,2);}return vx_set(action,1);
        }
    }
    if vw_explore==2 {return vx_sweep(action);}if vw_explore {return vx_explore(action);}return vx_search(action);
}
// The box never moves, so its last camera sighting is kept for the whole game.
// A remembered box not seen again within 0.9 m is forgotten and searched for.
fn vx_fetch_teacher(action) {
    let dock=pj_get(pj_get(ve_state,"case"),"dockVision");
    if pj_boolean(dock,"valid") && vc_json_int(dock,"frameId",0)==vc_json_int(ve_state,"totalSteps",0) {let p=pj_get(dock,"positionM");store64(vx_home,pj_real_node(pj_index(p,0)));store64(vx_home+8,pj_real_node(pj_index(p,1)));vx_home_seen=1;vx_home_step=ve_steps;if vx_carrying {vx_lost=0;}}
    vc_require(!pj_error,"invalid chase box sighting");if vw_explore && vx_carrying {let routed=vx_home_route(action);if routed>=0 {return routed;}}if !vx_carrying || !vx_home_seen {return vx_teacher(action);}
    let local=pj_get(pj_get(ve_state,"localization"),"pose");vc_require(pj_kind(local)==3 && pj_count(local)==3,"invalid chase localization");
    let dx=f64_sub(load64(vx_home),pj_real_node(pj_index(local,0)));let dy=f64_sub(load64(vx_home+8),pj_real_node(pj_index(local,1)));let distance=f64_hypot(dx,dy);let error=pb_wrap_pi(f64_sub(f64_atan2(dy,dx),pj_real_node(pj_index(local,2))));
    let recover=vx_recover(action);if recover>=0 {return recover;}
    if ve_steps-vx_home_step>15 && f64_lt(distance,vc_number(9,10)) {vx_home_seen=0;return vx_search(action);}
    if f64_gt(error,0) {vx_side=1;}else {vx_side=-1;}
    // Stop facing the box inside the simulator's 0.30-0.65 m docking window.
    if f64_lt(distance,vc_number(4,10)) {return vx_set(action,4);}
    if f64_lt(f64_magnitude(error),vc_number(3,10)) && f64_lt(distance,vc_number(58,100)) {return vx_set(action,6);}
    if f64_gt(f64_magnitude(error),vc_number(3,10)) && f64_lt(distance,vc_number(8,10)) {if vx_side>0 {return vx_set(action,5);}return vx_set(action,3);}
    if f64_gt(error,vc_number(2,10)) {return vx_set(action,0);}if f64_lt(error,vc_number(-2,10)) {return vx_set(action,2);}return vx_set(action,1);
}
fn vx_noise_next() {vx_noise_rng=(vx_noise_rng*1103515245+12345)&2147483647;return vx_noise_rng;}
// Sample one of the seven drive classes from the policy's logits.
fn vx_sample(logits,action) {
    let maximum=pb_read_float(logits);let i=1;while i<7 {maximum=pb_fmax(maximum,pb_read_float(logits+i*4));i=i+1;}
    let sum=0;i=0;while i<7 {sum=f64_add(sum,f64_exp(f64_sub(pb_read_float(logits+i*4),maximum)));i=i+1;}
    vx_sample_rng=(vx_sample_rng*1103515245+12345)&2147483647;let pick=f64_mul(sum,vc_number(vx_sample_rng>>7,16777216));
    i=0;while i<6 {pick=f64_sub(pick,f64_exp(f64_sub(pb_read_float(logits+i*4),maximum)));if !f64_gt(pick,0) {return vx_set(action,i);}i=i+1;}return vx_set(action,6);
}
// The most likely class, with the straight-ahead class (1) raised by
// --straight-bias hundredths once a search without the brick has lasted
// --straight-after steps since the last delivery.
fn vx_pick(logits,action) {
    let bias=0;if !vx_carrying && ve_steps-vx_place_step>=vw_straight_after {bias=vc_number(vw_straight_bias,100);}
    let best=0;let top=pb_read_float(logits);let i=1;
    while i<7 {let v=pb_read_float(logits+i*4);if i==1 {v=f64_add(v,bias);}if f64_gt(v,top) {top=v;best=i;}i=i+1;}return vx_set(action,best);
}
// --ensemble: every member policy keeps its own memory; the step takes the most
// likely class of the members' mean probabilities; with --ensemble-until, after that
// many steps without carrying or a delivery the main policy alone decides.
fn vx_accumulate(logits) {
    let top=pb_read_float(logits);let i=1;while i<7 {top=pb_fmax(top,pb_read_float(logits+i*4));i=i+1;}
    let sum=0;i=0;while i<7 {sum=f64_add(sum,f64_exp(f64_sub(pb_read_float(logits+i*4),top)));i=i+1;}
    i=0;while i<7 {store64(vx_mean+i*8,f64_add(load64(vx_mean+i*8),f64_div(f64_exp(f64_sub(pb_read_float(logits+i*4),top)),sum)));i=i+1;}return 0;
}
fn vx_ensemble(logits,action) {
    // Members overwrite the shared policy output, so the main policy's logits are taken first.
    pb_zero(vx_mean,7*8);vx_accumulate(logits);let alone=vw_ensemble_until && !vx_carrying && ve_steps-vx_place_step>=vw_ensemble_until;let main=ve_policy;let k=0;
    while k<vw_ensemble_count {ve_policy=load64(vx_members+k*8);let output=ve_action(vx_member_hidden+k*ve_memory_width*4,vw_blackout);if !alone {vx_accumulate(output);}k=k+1;}ve_policy=main;
    let best=0;let i=1;while i<7 {if f64_gt(load64(vx_mean+i*8),load64(vx_mean+best*8)) {best=i;}i=i+1;}return vx_set(action,best);
}
// Rewards: 0.5 for a pickup, 1 for a delivery and 0.3 for first reaching the
// brick's room when the brick appeared in another one.
fn vx_reward(step) {
    if vx_reward_place!=vx_place_step {vx_reward_place=vx_place_step;vx_reward_room=ve_room(vx_brick);if vx_reward_room>=0 && ve_room(ve_pose)==vx_reward_room {vx_reward_room=-1;}}
    if vx_reward_room>=0 && !vx_carrying && ve_room(ve_pose)==vx_reward_room {vx_reward_room=-1;store64(vx_rewards+step*8,f64_add(load64(vx_rewards+step*8),vc_number(3,10)));}return 0;
}
// Replace the action during a noise burst and report whether it did; bursts never stop the robot.
fn vx_noise(action) {
    if !vx_noise_left && (vx_noise_next()>>8)%1000<vw_action_noise*10 {vx_noise_left=2+(vx_noise_next()>>8)%5;vx_noise_class=(vx_noise_next()>>8)%6;}
    if vx_noise_left {vx_noise_left=vx_noise_left-1;vx_noisy=vx_noisy+1;vx_set(action,vx_noise_class);return 1;}return 0;
}
// One float32 row per step: step, true x, y, cos and sin of heading, carrying,
// brick detected now, steps since the last detection of this brick (300 when
// none), steps since it appeared, heading turned since then (rad), box and brick
// in the robot frame (forward, left; box distance), room, then the memory.
fn vx_memory_write(hidden) {
    let x=load64(ve_pose);let y=load64(ve_pose+8);let h=load64(ve_pose+16);let c=f64_cos(h);let s=f64_sin(h);
    let detections=pj_get(pj_get(pj_get(ve_state,"case"),"perception"),"detections");let seen=pj_kind(detections)==3 && pj_count(detections)>0;if seen {vx_memory_seen=ve_steps;}
    vx_memory_turn=f64_add(vx_memory_turn,f64_magnitude(pb_wrap_pi(f64_sub(h,vx_memory_heading))));vx_memory_heading=h;
    let since=300;if vx_memory_seen>=0 {since=pb_min(ve_steps-vx_memory_seen,300);}
    let bx=f64_sub(load64(vo_box),x);let by=f64_sub(load64(vo_box+8),y);let kx=f64_sub(load64(vx_brick),x);let ky=f64_sub(load64(vx_brick+8),y);if vx_carrying {kx=0;ky=0;}
    let values=alloc(16*8);let v=values;
    store64(v,f64_from_i64(ve_steps));store64(v+8,x);store64(v+16,y);store64(v+24,c);store64(v+32,s);store64(v+40,f64_from_i64(vx_carrying));store64(v+48,f64_from_i64(seen));store64(v+56,f64_from_i64(since));
    store64(v+64,f64_from_i64(pb_min(ve_steps-vx_place_step,300)));store64(v+72,vx_memory_turn);store64(v+80,f64_add(f64_mul(c,bx),f64_mul(s,by)));store64(v+88,f64_sub(f64_mul(c,by),f64_mul(s,bx)));
    store64(v+96,f64_hypot(bx,by));store64(v+104,f64_from_i64(vx_room(x)));store64(v+112,f64_add(f64_mul(c,kx),f64_mul(s,ky)));store64(v+120,f64_sub(f64_mul(c,ky),f64_mul(s,kx)));
    let i=0;while i<16 {pb_put32(vx_memory_row+i*4,pb_f64_to_f32(load64(values+i*8)));i=i+1;}vc_copy(vx_memory_row+64,hidden,ve_memory_width*4);syscall(11,values,128,0,0,0,0);
    vc_require(!pl_write(vx_memory_fd,vx_memory_row,64+ve_memory_width*4),"cannot write memory record");return 0;
}
// Evaluate the preceding complete 20-action window at the current pose.
// The episode also calls this once after the last command, when no next
// vx_track call would otherwise observe the final post-action pose.
fn vx_track_backforth() {
    let pose=vx_trail+(ve_steps%21)*24;store64(pose,load64(ve_pose));store64(pose+8,load64(ve_pose+8));store64(pose+16,load64(ve_pose+16));
    if ve_steps>=20 {let first=vx_trail+((ve_steps-20)%21)*24;let flips=0;let i=1;
        while i<20 {let a=load8(vx_trail+504+(ve_steps-20+i)%20);let c=load8(vx_trail+504+(ve_steps-21+i)%20);if a+c==2 && a!=c {flips=flips+1;}i=i+1;}
        if flips>=4 && f64_lt(f64_hypot(f64_sub(load64(pose),load64(first)),f64_sub(load64(pose+8),load64(first+8))),vc_number(25,100)) && f64_lt(f64_magnitude(pb_wrap_pi(f64_sub(load64(pose+16),load64(first+16)))),pb_radians(f64_from_i64(45))) {
            vx_backforth=vx_backforth+ve_steps-pb_max(vx_backforth_marked,ve_steps-20);vx_backforth_marked=ve_steps;}}return 0;
}
fn vx_track(action) {
    let bits=pb_u32(action+4);let steer=pb_u32(action);let drive=0;if bits&0x7fffffff {drive=1;if bits&0x80000000 {drive=-1;}}
    vx_track_backforth();
    store8(vx_trail+504+ve_steps%20,drive+1);
    let turn=0;if steer&0x7fffffff {turn=drive;if steer&0x80000000 {turn=0-drive;}}store8(vx_turns+ve_steps%6,turn+1);
    if drive && drive==0-vx_drive {vx_chain=vx_chain+1;}else {vx_chain=drive!=0;}vx_drive=drive;
    if vx_chain>=6 {let net=0;let i=0;while i<6 {net=net+load8(vx_turns+i)-1;i=i+1;}
        if net>=-1 && net<=1 {vx_pingpong=vx_pingpong+ve_steps-pb_max(vx_marked,ve_steps-6);vx_marked=ve_steps;}}return 0;
}
fn vx_result(path,seed,controller,checksum) {
    let out=alloc(4096);let b=alloc(32);pl_builder(b,out,4096);pl_text(b,"{\"seed\":");pl_int(b,seed);pl_text(b,",\"game\":");if vw_fetch {pj_text(b,"fetch");}else {pj_text(b,"chase");}pl_text(b,",\"controller\":");pj_text(b,controller);
    pl_text(b,",\"reaches\":");pl_int(b,vx_reaches);if vw_fetch {pl_text(b,",\"deliveries\":");pl_int(b,vx_deliveries);pl_text(b,",\"deliveriesPerMinute\":");pl_float(b,f64_div(f64_from_i64(vx_deliveries*300),f64_from_i64(pb_max(ve_steps,1))));}pl_text(b,",\"jumps\":");pl_int(b,vx_jumps);pl_text(b,",\"steps\":");pl_int(b,ve_steps);pl_text(b,",\"actionSeconds\":");pl_float(b,vc_number(ve_steps,5));
    pl_text(b,",\"reachesPerMinute\":");pl_float(b,f64_div(f64_from_i64(vx_reaches*300),f64_from_i64(pb_max(ve_steps,1))));pl_text(b,",\"contactSteps\":");pl_int(b,vx_contacts);pl_text(b,",\"pingPongSteps\":");pl_int(b,vx_pingpong);pl_text(b,",\"backForthSteps\":");pl_int(b,vx_backforth);pl_text(b,",\"backForthMetric\":\"pose20-final-inclusive-v2\"");pl_text(b,",\"teacherDisagreements\":");pl_int(b,vx_disagree);pl_text(b,",\"pathM\":");pl_float(b,ve_path);
    pl_text(b,",\"blackout\":");pj_bool_text(b,vw_blackout);pl_text(b,",\"policyWeightsSHA256\":");if checksum {pj_text(b,checksum);}else {pl_text(b,"null");}pl_text(b,",\"farBricks\":");pj_bool_text(b,vw_far_bricks);pl_text(b,",\"level\":");pl_int(b,vw_level);if vw_level {pl_text(b,",\"levelPlacement\":");vx_level_name(b);}if vw_straight_bias {pl_text(b,",\"straightBiasHundredths\":");pl_int(b,vw_straight_bias);pl_text(b,",\"straightAfterSteps\":");pl_int(b,vw_straight_after);}if vw_door_pass {pl_text(b,",\"doorPass\":true");}if vw_ensemble_count {pl_text(b,",\"ensembleMembers\":");pl_int(b,vw_ensemble_count+1);}if vw_ensemble_until {pl_text(b,",\"ensembleUntilSteps\":");pl_int(b,vw_ensemble_until);}if vw_door_early {pl_text(b,",\"doorEarly\":true");}if vw_action_noise {pl_text(b,",\"actionNoisePercent\":");pl_int(b,vw_action_noise);pl_text(b,",\"noisySteps\":");pl_int(b,vx_noisy);}if vw_self_keep {pl_text(b,",\"selfImitationKeepSteps\":");pl_int(b,vw_self_keep);pl_text(b,",\"selfImitationRows\":");pl_int(b,vx_kept);}if vw_sample_actions {pl_text(b,",\"sampledActions\":true,\"returnSum\":");pl_float(b,vx_returns);}pl_text(b,",\"exploreTeacher\":");pj_bool_text(b,vw_explore==1);pl_text(b,",\"sweepTeacher\":");pj_bool_text(b,vw_explore==2);if vw_explore==1 {pl_text(b,",\"coverageMisses\":");pl_int(b,vx_misses);}pl_text(b,",\"maximumBrickDistanceM\":0.35,\"suppliedMap\":false,\"taskEventHint\":false,\"carryCue\":");pj_bool_text(b,vw_fetch && !vw_hide_carry);pl_text(b,"}\n");
    vc_require(!load64(b+24),"chase result exceeded limit");vc_write(path,out,load64(b+8));pl_write(1,out,load64(b+8));return out;
}
// Modes: 0 camera teacher, 1 neural policy, 2 always forward, 3 neural policy drives while the teacher labels.
// Dataset rows are written before each action and always carry the teacher's label.
fn vx_episode(directory,scene,seed,mode,base,hidden) {
    ve_task=3;ve_open(vw_binary("simulator"),directory,scene,vw_template(),seed,0);vx_world(directory);
    vx_rng=(seed*7919+17)&2147483647;if !vx_rng {vx_rng=1;}if !vx_brick {vx_brick=alloc(16);vx_target=alloc(16);}
    vx_reaches=0;vx_jumps=0;vx_disagree=0;vx_seen_step=-1000;vx_missing=0;vx_escape=0;vx_contacts=0;vx_drive=0;vx_chain=0;vx_pingpong=0;vx_marked=-1;if !vx_turns {vx_turns=alloc(8);vx_trail=alloc(528);}vx_backforth=0;vx_backforth_marked=-1;vx_side=1;vx_last_class=-1;vx_deliveries=0;vx_carrying=0;vx_search_carry=0;vx_search_from=0;vx_home_seen=0;vx_home_step=-1000;vx_lost=0;vx_stuck=0;vx_goal=-1;vx_misses=0;vx_noise_rng=(seed*48271+11)&2147483647;vx_noise_left=0;vx_noisy=0;vx_kept=0;vx_sample_rng=(seed*69621+7)&2147483647;if !vx_sample_rng {vx_sample_rng=1;}vx_reward_place=-1;vx_reward_room=-1;vx_returns=0;if !vx_rewards {vx_rewards=alloc(1000*8);}pb_zero(vx_rewards,1000*8);if !vx_home {vx_home=alloc(16);}if !vx_noise_marks {vx_noise_marks=alloc(512);}
    vx_log=syscall(2,vc_path(directory,"chase.jsonl"),0x800c1,384,0,0,0);vc_require(vx_log>=0,"cannot create chase journal");
    if vw_record_memory {vx_memory_fd=syscall(2,vc_path(directory,"memory.bin"),0x800c1,384,0,0,0);vc_require(vx_memory_fd>=0,"cannot create memory record");if !vx_memory_row {vx_memory_row=alloc(64+256*4);}}if vw_fetch {vx_place_fetch("start");}else {vx_place("start");}let action=alloc(8);let label=alloc(8);
    while ve_steps<vw_horizon {
        if vw_fetch {let cue=0;if vx_carrying && !vw_hide_carry {cue=0x3f800000;}if vw_search_cue {let carry=vx_carrying!=0;if carry!=vx_search_carry {vx_search_carry=carry;vx_search_from=ve_steps;}cue=vd_search_cue(carry,ve_steps-vx_search_from);}pb_put32(ve_feedback+24,cue);}
        if (mode==0 || mode==3) && vw_fetch {vx_fetch_teacher(label);vc_copy(action,label,8);}else if mode==0 || mode==3 {vx_teacher(label);vc_copy(action,label,8);}if mode==1 || mode==3 {let output=ve_action(hidden,vw_blackout);if vw_sample_actions {vx_sample(output,action);}else if vw_ensemble_count {vx_ensemble(output,action);}else if vw_straight_bias {vx_pick(output,action);}else {vc_copy(action,output,8);}}if mode==2 {vx_set(action,1);}
        if vw_action_noise {store8(vx_noise_marks+ve_steps,vx_noise(action));}
        if mode==3 && load64(action)!=load64(label) {vx_disagree=vx_disagree+1;}
        if vw_self_keep || vw_sample_actions {vc_copy(label,action,8);}
        if vw_record_memory && mode==1 {vx_memory_write(hidden);}
        if base {vc_copy(base+ve_steps*21168,ve_image,21168);let row=base+vw_horizon*21168+ve_steps*44;vc_copy(row,ve_feedback,28);vc_copy(row+28,label,8);pb_put32(row+36,0);if vw_self_keep {pb_put32(row+40,0);}else {pb_put32(row+40,0x3f800000);}if vw_record_map {vx_map_row(vx_map_base+ve_steps*144);}}
        if ve_contact {vx_contacts=vx_contacts+1;}vx_track(action);ve_step(action);
        if vw_fetch {
            if vw_sample_actions {vx_reward(ve_steps-1);}
            if !vx_carrying && vc_json_int(ve_state,"findReturn","consumedIndex")>=0 {vx_reaches=vx_reaches+1;vx_carrying=1;vx_lost=0;if vw_sample_actions {store64(vx_rewards+(ve_steps-1)*8,f64_add(load64(vx_rewards+(ve_steps-1)*8),vc_number(1,2)));}}
            if vc_json_int(ve_state,"findReturn","deliveries")>vx_deliveries {vx_deliveries=vx_deliveries+1;vx_carrying=0;vx_lost=0;if vw_sample_actions {store64(vx_rewards+(ve_steps-1)*8,f64_add(load64(vx_rewards+(ve_steps-1)*8),PB_ONE));}
                // Self-imitation keeps the quick cycle, from the brick appearing to its delivery, except the random noise steps.
                if base && vw_self_keep && ve_steps-vx_place_step<=vw_self_keep {let t=vx_place_step;while t<ve_steps {if !vw_action_noise || !load8(vx_noise_marks+t) {pb_put32(base+vw_horizon*21168+t*44+40,0x3f800000);vx_kept=vx_kept+1;}t=t+1;}}
                vx_place_fetch("delivery");}
        }
        else if vc_json_int(ve_state,"findReturn","consumedIndex")>=0 {vx_reaches=vx_reaches+1;vx_place("reach");}
        else if ve_steps==vx_jump_step && f64_gt(f64_hypot(f64_sub(load64(vx_brick),load64(ve_pose)),f64_sub(load64(vx_brick+8),load64(ve_pose+8))),vc_number(9,10)) {vx_jumps=vx_jumps+1;vx_place("jump");}
    }
    // Include the final window, whose post-action pose has no following action.
    vx_track_backforth();
    // Each row's weight becomes its discounted return (factor 0.99 per action); the trainer reweights it later.
    if base && vw_sample_actions {let g=0;let t=vw_horizon-1;while t>=0 {g=f64_add(load64(vx_rewards+t*8),f64_mul(vc_number(99,100),g));pb_put32(base+vw_horizon*21168+t*44+40,pb_f64_to_f32(g));vx_returns=f64_add(vx_returns,g);t=t-1;}}
    syscall(3,vx_log,0,0,0,0,0);if vw_record_memory {syscall(3,vx_memory_fd,0,0,0,0,0);}return 0;
}
fn vx_scene(episode) {if vw_catalog {return vc_path(vw_catalog,vc_int(episode));}return vw_scene;}
fn vx_collect() {
    vc_require(vw_validation>=1 && vw_episodes>vw_validation && vw_episodes<=128,"chase collect requires 2..128 episodes and a smaller positive validation count");vc_require(vw_horizon<=512,"collection horizon must be in 1..512");vc_mkdir(vw_output);
    let size=32+vw_episodes*vw_horizon*(21168+44);let path=vc_path(vw_output,"data.partial.bin");let fd=syscall(2,path,0x800c2,384,0,0,0);vc_require(fd>=0 && !syscall(77,fd,size,0,0,0,0),"cannot allocate chase dataset");
    let dataset=syscall(9,0,size,3,1,fd,0);vc_require(dataset>0,"cannot map chase dataset");vc_copy(dataset,"PVDATA01",8);store64(dataset+8,vw_episodes);store64(dataset+16,vw_episodes-vw_validation);store64(dataset+24,vw_horizon);
    let map_size=32+vw_episodes*vw_horizon*144;let map_path=vc_path(vw_output,"map.partial.bin");let map_fd=-1;let map=0;
    if vw_record_map {map_fd=syscall(2,map_path,0x800c2,384,0,0,0);vc_require(map_fd>=0 && !syscall(77,map_fd,map_size,0,0,0,0),"cannot allocate coverage maps");map=syscall(9,0,map_size,3,1,map_fd,0);vc_require(map>0,"cannot map coverage maps");vc_copy(map,"PVMAP001",8);store64(map+8,vw_episodes);store64(map+16,vw_episodes-vw_validation);store64(map+24,vw_horizon);}
    let episode=0;let reaches=0;let mode=0;let checksum=0;let controller="camera-sighting chase teacher";if vw_explore==1 {controller="exploring fetch teacher";}if vw_explore==2 {controller="sweeping fetch teacher";}let teacher=controller;let hidden=alloc(ve_memory_width*4);
    if vw_policy {let frozen=vc_path(vw_output,"policy");vw_snapshot_policy(vw_policy,frozen);checksum=ve_policy_open(frozen,vw_output);mode=3;controller="native neural policy with chase teacher labels";if vw_explore==1 {controller="native neural policy with exploring fetch teacher labels";}if vw_explore==2 {controller="native neural policy with sweeping fetch teacher labels";}}
    while episode<vw_episodes {
        let directory=vc_path(vw_output,vc_concat("expert-",vc_int(episode)));pb_zero(hidden,ve_memory_width*4);if map {vx_map_base=map+32+episode*vw_horizon*144;}vx_episode(directory,vx_scene(episode),vw_seed+episode,mode,dataset+32+episode*vw_horizon*(21168+44),hidden);
        reaches=reaches+vx_reaches;vx_result(vc_path(directory,"result.json"),vw_seed+episode,controller,checksum);ve_close();vo_close();episode=episode+1;
    }
    if mode==3 {vc_finish(ve_policy,15000);}
    vc_require(!syscall(26,dataset,size,4,0,0,0) && !syscall(74,fd,0,0,0,0,0),"cannot synchronize chase dataset");syscall(11,dataset,size,0,0,0,0);syscall(3,fd,0,0,0,0,0);
    vc_require(!syscall(82,path,vc_path(vw_output,"data.bin"),0,0,0,0),"cannot publish chase demonstrations");
    if map {vc_require(!syscall(26,map,map_size,4,0,0,0) && !syscall(74,map_fd,0,0,0,0,0),"cannot synchronize coverage maps");syscall(11,map,map_size,0,0,0,0);syscall(3,map_fd,0,0,0,0,0);vc_require(!syscall(82,map_path,vc_path(vw_output,"map.bin"),0,0,0,0),"cannot publish coverage maps");}
    let out=alloc(4096);let b=alloc(32);pl_builder(b,out,4096);pl_text(b,"{\"complete\":true,\"game\":\"chase\",\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"teacher\":");pj_text(b,teacher);pl_text(b,",\"studentDriven\":");pj_bool_text(b,mode==3);pl_text(b,",\"teacherUsesCameraDetections\":true,\"teacherUsesReferenceGeometryForWallsOnly\":true,\"teacherUsesTargetCoordinates\":false,\"actorUsesReferencePose\":false,\"actorUsesTargetCoordinates\":false,\"seed\":");pl_int(b,vw_seed);
    pl_text(b,",\"episodes\":");pl_int(b,vw_episodes);pl_text(b,",\"reaches\":");pl_int(b,reaches);pl_text(b,",\"trainingEpisodes\":");pl_int(b,vw_episodes-vw_validation);pl_text(b,",\"validationEpisodes\":");pl_int(b,vw_validation);pl_text(b,",\"sequenceLength\":");pl_int(b,vw_horizon);pl_text(b,",\"dataSHA256\":");pj_text(b,vc_file_sha(vc_path(vw_output,"data.bin")));if map {pl_text(b,",\"mapSHA256\":");pj_text(b,vc_file_sha(vc_path(vw_output,"map.bin")));}pl_text(b,"}\n");vc_write(vc_path(vw_output,"report.json"),out,load64(b+8));return 0;
}
fn vx_run() {
    vc_mkdir(vw_output);let checksum=0;let mode=2;let controller="always forward";let hidden=alloc(ve_memory_width*4);
    if !vw_chase_forward {vc_require(vw_policy,"chase run requires --policy DIRECTORY or --chase-forward");if vw_ensemble_count {vx_members=alloc(vw_ensemble_count*8);vx_member_hidden=alloc(vw_ensemble_count*ve_memory_width*4);vx_mean=alloc(7*8);let k=0;
        while k<vw_ensemble_count {let dir=vc_path(vw_output,vc_concat("member-",vc_int(k)));vc_mkdir(dir);let copy=vc_path(dir,"policy");vw_snapshot_policy(load64(vw_ensemble+k*8),copy);ve_policy_open(copy,dir);store64(vx_members+k*8,ve_policy);k=k+1;}}
        let frozen=vc_path(vw_output,"policy");vw_snapshot_policy(vw_policy,frozen);checksum=ve_policy_open(frozen,vw_output);mode=1;controller="native neural policy";}
    let rows=alloc(131072);let b=alloc(32);pl_builder(b,rows,131072);pl_char(b,91);let episode=0;let reaches=0;
    while episode<vw_episodes {
        let seed=vw_seed+episode;let directory=vc_path(vw_output,vc_int(seed));pb_zero(hidden,ve_memory_width*4);if vw_ensemble_count {pb_zero(vx_member_hidden,vw_ensemble_count*ve_memory_width*4);}vx_episode(directory,vx_scene(episode),seed,mode,0,hidden);reaches=reaches+vx_reaches;
        let result=vx_result(vc_path(directory,"result.json"),seed,controller,checksum);ve_close();vo_close();if episode {pl_char(b,44);}pl_text(b,result);episode=episode+1;
    }
    pl_char(b,93);if mode==1 {vc_finish(ve_policy,15000);let k=0;while k<vw_ensemble_count {vc_finish(load64(vx_members+k*8),15000);k=k+1;}}vc_require(!load64(b+24),"chase summary exceeded limit");let out=alloc(139264);let s=alloc(32);pl_builder(s,out,139264);
    pl_text(s,"{\"complete\":true,\"game\":\"chase\",\"episodes\":");pl_int(s,vw_episodes);pl_text(s,",\"reaches\":");pl_int(s,reaches);pl_text(s,",\"controller\":");pj_text(s,controller);pl_text(s,",\"blackout\":");pj_bool_text(s,vw_blackout);
    pl_text(s,",\"policyWeightsSHA256\":");if checksum {pj_text(s,checksum);}else {pl_text(s,"null");}pl_text(s,",\"rows\":");pl_append(s,rows,load64(b+8));pl_text(s,"}\n");
    vc_require(!load64(s+24),"cannot construct chase summary");vc_write(vc_path(vw_output,"summary.json"),out,load64(s+8));return 0;
}
