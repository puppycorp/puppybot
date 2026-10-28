// Training-only room coverage goals. This planner reads room bounds, never the
// brick's position. The actor receives none of these goals or room bounds.
import "host.flex";

fn sx_point(rooms,count,start,index,out) {
    vc_require(count>=1 && count<=64 && start>=0 && start<count && index>=0,"invalid coverage goal dimensions");
    let ordinal=index%(count*9);let room=(start+ordinal/9)%count;let cell=ordinal%9;let row=cell/3;let col=cell%3;if row==1 {col=2-col;}
    let bounds=rooms+room*32;let width=f64_sub(load64(bounds+16),load64(bounds));let height=f64_sub(load64(bounds+24),load64(bounds+8));
    vc_require(f64_gt(width,0) && f64_gt(height,0),"invalid coverage room bounds");
    store64(out,f64_add(load64(bounds),f64_mul(width,vc_number(col+1,4))));store64(out+8,f64_add(load64(bounds+8),f64_mul(height,vc_number(row+1,4))));return 0;
}
fn sx_goal(rooms,count,start,index,out) {
    sx_point(rooms,count,start,index,out);let next=alloc(16);sx_point(rooms,count,start,index+1,next);
    store64(out+16,f64_atan2(f64_sub(load64(next+8),load64(out+8)),f64_sub(load64(next),load64(out))));syscall(11,next,16,0,0,0,0);return 0;
}
// Visit another room early when one exists. In one-room scenes, begin with a
// nearby point substantially ahead instead of a fixed corner behind the base.
fn sx_start(rooms,count,start,pose) {
    let best=0;let distance_best=f64_from_i64(100000);let found=0;let point=alloc(16);let i=0;let c=f64_cos(load64(pose+16));let s=f64_sin(load64(pose+16));
    if count>1 {i=9;while i<count*9 {sx_point(rooms,count,start,i,point);let dx=f64_sub(load64(point),load64(pose));let dy=f64_sub(load64(point+8),load64(pose+8));let distance=f64_hypot(dx,dy);let forward=f64_add(f64_mul(c,dx),f64_mul(s,dy));
        if f64_gt(distance,vc_number(4,10)) && f64_gt(forward,f64_mul(distance,vc_number(5,10))) && f64_lt(distance,distance_best) {best=i;distance_best=distance;found=1;}i=i+1;
    }}
    i=0;if !found {while i<9 {sx_point(rooms,count,start,i,point);let dx=f64_sub(load64(point),load64(pose));let dy=f64_sub(load64(point+8),load64(pose+8));let distance=f64_hypot(dx,dy);let forward=f64_add(f64_mul(c,dx),f64_mul(s,dy));
        if f64_gt(distance,vc_number(4,10)) && f64_gt(forward,f64_mul(distance,vc_number(5,10))) && f64_lt(distance,distance_best) {best=i;distance_best=distance;found=1;}i=i+1;
    }}syscall(11,point,16,0,0,0,0);if found {return best;}return 0;
}
fn sx_coverage_goal(rooms,count,start,pose,first,index,out) {
    sx_goal(rooms,count,start,index,out);if index==first {store64(out+16,load64(pose+16));}return 0;
}
// The component detector reports its ground point in the estimated local
// frame. Only this camera-derived point, not a prop position, may interrupt
// coverage. The simulator's true pose converts the goal for its oracle API.
fn sx_camera_goal(state,pose,out) {
    let perception=pj_get(pj_get(state,"case"),"perception");let detections=pj_get(perception,"detections");if pj_kind(detections)!=3 || !pj_count(detections) {return 0;}
    vc_require(vc_json_int(perception,"frameId",0)==vc_json_int(state,"totalSteps",0),"coverage teacher received a stale camera detection");
    let local=pj_get(pj_get(state,"localization"),"pose");let point=pj_get(pj_index(detections,0),"targetM");vc_require(pj_kind(local)==3 && pj_count(local)==3 && pj_kind(point)==3 && pj_count(point)==3,"invalid camera target or localization");
    let lx=pj_real_node(pj_index(local,0));let ly=pj_real_node(pj_index(local,1));let heading=pj_real_node(pj_index(local,2));let x=pj_real_node(pj_index(point,0));let y=pj_real_node(pj_index(point,1));vc_require(!pj_error && f64_is_finite(x) && f64_is_finite(y) && f64_is_finite(lx) && f64_is_finite(ly) && f64_is_finite(heading),"invalid camera target coordinates");
    let dx=f64_sub(x,lx);let dy=f64_sub(y,ly);let distance=f64_hypot(dx,dy);if f64_lt(distance,vc_number(3,10)) || f64_gt(distance,vc_number(2,1)) {return 0;}
    let c=f64_cos(heading);let s=f64_sin(heading);let forward=f64_add(f64_mul(c,dx),f64_mul(s,dy));let lateral=f64_sub(f64_mul(c,dy),f64_mul(s,dx));let actual=load64(pose+16);c=f64_cos(actual);s=f64_sin(actual);
    dx=f64_sub(f64_mul(c,forward),f64_mul(s,lateral));dy=f64_add(f64_mul(s,forward),f64_mul(c,lateral));let angle=f64_atan2(dy,dx);let range=vc_number(24,100);
    store64(out,f64_add(load64(pose),f64_sub(dx,f64_mul(range,f64_cos(angle)))));store64(out+8,f64_add(load64(pose+8),f64_sub(dy,f64_mul(range,f64_sin(angle)))));store64(out+16,angle);return 1;
}
