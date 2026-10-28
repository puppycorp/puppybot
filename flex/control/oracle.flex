// Training-only full-scene route planning. None of this state is an actor input.
import "environment.flex";
global vo_world=0;
global vo_world_size=0;
global vo_width=0;
global vo_height=0;
global vo_grid=0;
global vo_distance=0;
global vo_queue=0;
global vo_route=0;
global vo_count=0;
global vo_at=0;
global vo_clearance=0;
global vo_box=0;
global vo_target_x=0;
global vo_target_y=0;
fn vo_x(col) {return f64_add(load64(vo_world+64),vc_number(col*2+1,20));}
fn vo_y(row) {return f64_add(load64(vo_world+72),vc_number(row*2+1,20));}
fn vo_cell(x,y) {
    let col=f64_to_i64_nearest(f64_sub(f64_mul(f64_sub(x,load64(vo_world+64)),f64_from_i64(10)),vc_number(1,2)));
    let row=f64_to_i64_nearest(f64_sub(f64_mul(f64_sub(y,load64(vo_world+72)),f64_from_i64(10)),vc_number(1,2)));
    if col<0 || row<0 || col>=vo_width || row>=vo_height {return -1;}return row*vo_width+col;
}
fn vo_free(x,y) {
    let margin=vo_clearance;
    if f64_lt(x,f64_add(load64(vo_world+64),margin)) || f64_gt(x,f64_sub(load64(vo_world+80),margin)) || f64_lt(y,f64_add(load64(vo_world+72),margin)) || f64_gt(y,f64_sub(load64(vo_world+88),margin)) {return 0;}
    let i=0;while i<load64(vo_world+8) {
        let r=vo_world+256+i*128;let dx=f64_sub(x,load64(r+48));let dy=f64_sub(y,load64(r+56));let c=f64_cos(load64(r+96));let s=f64_sin(load64(r+96));
        let local_x=f64_add(f64_mul(c,dx),f64_mul(s,dy));let local_y=f64_sub(f64_mul(c,dy),f64_mul(s,dx));
        if f64_lt(f64_magnitude(local_x),f64_add(load64(r+72),margin)) && f64_lt(f64_magnitude(local_y),f64_add(load64(r+80),margin)) {return 0;}i=i+1;
    }
    // Include the collection box; its true pose/size is privileged too.
    if f64_lt(f64_magnitude(f64_sub(x,load64(vo_box))),f64_add(load64(vo_box+16),margin)) && f64_lt(f64_magnitude(f64_sub(y,load64(vo_box+8))),f64_add(load64(vo_box+24),margin)) {return 0;}return 1;
}
fn vo_line(ax,ay,bx,by) {
    let dx=f64_sub(bx,ax);let dy=f64_sub(by,ay);let count=f64_to_i64_nearest(f64_mul(f64_hypot(dx,dy),f64_from_i64(50)))+1;let i=0;
    while i<=count {let t=vc_number(i,count);if !vo_free(f64_add(ax,f64_mul(dx,t)),f64_add(ay,f64_mul(dy,t))) {return 0;}i=i+1;}return 1;
}
fn vo_close() {
    if vo_world {syscall(11,vo_world,vo_world_size,0,0,0,0);let cells=vo_width*vo_height;syscall(11,vo_grid,cells,0,0,0,0);syscall(11,vo_distance,cells*8,0,0,0,0);syscall(11,vo_queue,cells*8,0,0,0,0);syscall(11,vo_route,cells*16,0,0,0,0);vo_world=0;}return 0;
}
fn vo_open(directory) {
    vo_close();let old=pj_arena;let used=pj_used;pj_arena=alloc(131072);let root=vc_json_file(vc_path(vc_path(directory,"scene"),"case.json"));
    let target=pj_get(pj_index(pj_get(root,"objects"),0),"position");vo_target_x=pj_real_node(pj_index(target,0));vo_target_y=pj_real_node(pj_index(target,1));
    let box=pj_get(root,"container");let position=pj_get(box,"position");let size=pj_get(box,"innerSize");let wall=pj_real_node(pj_get(box,"wallThickness"));if !vo_box {vo_box=alloc(32);}
    store64(vo_box,pj_real_node(pj_index(position,0)));store64(vo_box+8,pj_real_node(pj_index(position,1)));store64(vo_box+16,f64_add(f64_mul(pj_real_node(pj_index(size,0)),vc_number(1,2)),wall));store64(vo_box+24,f64_add(f64_mul(pj_real_node(pj_index(size,1)),vc_number(1,2)),wall));vc_require(!pj_error,"invalid oracle target/box reference");
    syscall(11,pj_arena,131072,0,0,0,0);pj_arena=old;pj_used=used;vo_world=vc_map(vc_path(vc_path(directory,"scene"),"environment.bin"));vo_world_size=vc_size;vc_require(vo_world_size>=256 && load64(vo_world)==load64("PBENV001") && load64(vo_world+8)>=0 && load64(vo_world+8)<=128 && vo_world_size>=256+load64(vo_world+8)*128,"invalid oracle environment");
    vo_width=f64_to_i64_nearest(f64_mul(f64_sub(load64(vo_world+80),load64(vo_world+64)),f64_from_i64(10)));vo_height=f64_to_i64_nearest(f64_mul(f64_sub(load64(vo_world+88),load64(vo_world+72)),f64_from_i64(10)));
    vc_require(vo_width>=1 && vo_height>=1 && vo_width<=400 && vo_height<=400,"oracle floor bounds exceed 40 m");let cells=vo_width*vo_height;vo_grid=alloc(cells);vo_distance=alloc(cells*8);vo_queue=alloc(cells*8);vo_route=alloc(cells*16);vo_clearance=vc_number(24,100);
    let i=0;while i<cells {store8(vo_grid+i,vo_free(vo_x(i%vo_width),vo_y(i/vo_width)));store64(vo_distance+i*8,-1);i=i+1;}
    let tx=vo_target_x;let ty=vo_target_y;
    let goal=vo_cell(tx,ty);let start=vo_cell(load64(ve_pose),load64(ve_pose+8));vc_require(start>=0 && goal>=0 && load8(vo_grid+start) && load8(vo_grid+goal),"oracle start/target lacks chassis clearance");
    store64(vo_distance+goal*8,0);store64(vo_queue,goal);let head=0;let tail=1;
    while head<tail {
        let cell=load64(vo_queue+head*8);head=head+1;let k=0;
        while k<4 {let next=cell-vo_width;if k==1 {next=cell+vo_width;}if k==2 {next=cell-1;}if k==3 {next=cell+1;}
            let same_row=k<2 || (next>=0 && next/vo_width==cell/vo_width);
            if next>=0 && next<cells && same_row && load8(vo_grid+next) && load64(vo_distance+next*8)<0 {store64(vo_distance+next*8,load64(vo_distance+cell*8)+1);store64(vo_queue+tail*8,next);tail=tail+1;}k=k+1;
        }
    }
    vc_require(load64(vo_distance+start*8)>=0,"oracle target is unreachable in the inflated reference floorplan");vo_count=0;vo_at=0;let cell=start;
    while cell!=goal {
        store64(vo_route+vo_count*16,vo_x(cell%vo_width));store64(vo_route+vo_count*16+8,vo_y(cell/vo_width));vo_count=vo_count+1;let best=cell;let k=0;
        while k<4 {let next=cell-vo_width;if k==1 {next=cell+vo_width;}if k==2 {next=cell-1;}if k==3 {next=cell+1;}
            if next>=0 && next<cells && (k<2 || next/vo_width==cell/vo_width) && load64(vo_distance+next*8)>=0 && load64(vo_distance+next*8)<load64(vo_distance+best*8) {best=next;}k=k+1;
        }vc_require(best!=cell && vo_count<cells,"oracle route extraction stalled");cell=best;
    }
    store64(vo_route+vo_count*16,tx);store64(vo_route+vo_count*16+8,ty);vo_count=vo_count+1;
    // Reference route is an audit artifact, never a dataset input.
    let text=alloc(cells*64+1024);let b=alloc(32);pl_builder(b,text,cells*64+1024);pl_text(b,"{\"teacher\":\"full-scene oracle\",\"actorReceivesPlan\":false,\"clearanceM\":0.24,\"waypoints\":[");i=0;
    while i<vo_count {if i {pl_char(b,44);}pl_char(b,91);pl_float(b,load64(vo_route+i*16));pl_char(b,44);pl_float(b,load64(vo_route+i*16+8));pl_char(b,93);i=i+1;}
    pl_text(b,"]}\n");vc_require(!load64(b+24),"oracle route receipt exceeded capacity");vc_write(vc_path(directory,"oracle.json"),text,load64(b+8));syscall(11,text,cells*64+1024,0,0,0,0);syscall(11,b,32,0,0,0,0);return 0;
}
fn vo_action(action,history,count,reverse,speed) {
    pb_zero(action,8);if ve_found {if reverse<count {vc_copy(action,history+(count-1-reverse)*8,8);pb_put32(action+4,pb_u32(action+4)^0x80000000);}return 0;}
    let x=load64(ve_pose);let y=load64(ve_pose+8);let nearest=vo_at;let best=f64_hypot(f64_sub(load64(vo_route+nearest*16),x),f64_sub(load64(vo_route+nearest*16+8),y));let i=vo_at+1;
    while i<vo_count && i<vo_at+12 {let distance=f64_hypot(f64_sub(load64(vo_route+i*16),x),f64_sub(load64(vo_route+i*16+8),y));if f64_lt(distance,best) {best=distance;nearest=i;}i=i+1;}vo_at=nearest;
    let aim=vo_at;let stopped=0;i=vo_at+1;while i<vo_count && !stopped {let px=load64(vo_route+i*16);let py=load64(vo_route+i*16+8);let distance=f64_hypot(f64_sub(px,x),f64_sub(py,y));if f64_gt(distance,vc_number(45,100)) || !vo_line(x,y,px,py) {stopped=1;}else {aim=i;}i=i+1;}
    let dx=f64_sub(load64(vo_route+aim*16),x);let dy=f64_sub(load64(vo_route+aim*16+8),y);let distance=pb_fmax(vc_number(12,100),f64_hypot(dx,dy));let error=pb_wrap_pi(f64_sub(f64_atan2(dy,dx),load64(ve_pose+16)));
    let steering=pb_neg(f64_div(f64_atan(f64_div(f64_mul(vc_number(36,100),f64_sin(error)),distance)),pb_radians(f64_from_i64(45))));
    pb_put32(action,pb_f64_to_f32(pb_fclamp(steering,pb_neg(PB_ONE),PB_ONE)));pb_put32(action+4,pb_f64_to_f32(speed));vc_copy(history+count*8,action,8);return 0;
}
