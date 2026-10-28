// The teacher's room sweep must be deterministic and independent of props.
import "../control/exploration-teacher.flex";
fn st_close(a,b) {return f64_lt(f64_magnitude(f64_sub(a,b)),vc_number(1,1000000));}
fn main(argc,argv) {
    vc_init(argc,argv);let rooms=alloc(64);store64(rooms,vc_number(0,1));store64(rooms+8,vc_number(0,1));store64(rooms+16,vc_number(4,1));store64(rooms+24,vc_number(4,1));
    store64(rooms+32,vc_number(4,1));store64(rooms+40,vc_number(0,1));store64(rooms+48,vc_number(8,1));store64(rooms+56,vc_number(4,1));
    let goal=alloc(24);sx_goal(rooms,2,0,0,goal);vc_require(st_close(load64(goal),vc_number(1,1)) && st_close(load64(goal+8),vc_number(1,1)) && st_close(load64(goal+16),0),"wrong first sweep point");
    sx_goal(rooms,2,0,3,goal);vc_require(st_close(load64(goal),vc_number(3,1)) && st_close(load64(goal+8),vc_number(2,1)),"coverage row does not reverse");
    sx_goal(rooms,2,1,0,goal);vc_require(st_close(load64(goal),vc_number(5,1)) && st_close(load64(goal+8),vc_number(1,1)),"coverage did not start in requested room");
    sx_goal(rooms,2,0,9,goal);vc_require(st_close(load64(goal),vc_number(5,1)) && st_close(load64(goal+8),vc_number(1,1)),"coverage did not advance to the next room");
    let duplicate=alloc(24);sx_goal(rooms,2,0,18,duplicate);sx_goal(rooms,2,0,0,goal);vc_require(load64(goal)==load64(duplicate) && load64(goal+8)==load64(duplicate+8) && load64(goal+16)==load64(duplicate+16),"coverage cycle is not deterministic");
    let start_pose=alloc(24);store64(start_pose,vc_number(2,1));store64(start_pose+8,vc_number(2,1));store64(start_pose+16,0);let first=sx_start(rooms,2,0,start_pose);sx_goal(rooms,2,0,first,goal);vc_require(first>=9 && f64_gt(load64(goal),load64(rooms+32)) && st_close(load64(goal+8),load64(start_pose+8)),"coverage did not visit the forward adjacent room first");
    first=sx_start(rooms,1,0,start_pose);sx_goal(rooms,1,0,first,goal);vc_require(f64_gt(load64(goal),load64(start_pose)) && st_close(load64(goal+8),load64(start_pose+8)),"single-room coverage did not begin ahead of the robot");
    let text="{\"totalSteps\":1,\"case\":{\"perception\":{\"frameId\":1,\"detections\":[{\"targetM\":[1,0,0]}]}},\"localization\":{\"pose\":[0,0,0]}}";let state=pj_parse(text,pl_size(text));let pose=alloc(24);store64(pose,vc_number(5,1));store64(pose+8,vc_number(5,1));store64(pose+16,vc_number(1570796327,1000000000));
    vc_require(sx_camera_goal(state,pose,goal) && st_close(load64(goal),vc_number(5,1)) && st_close(load64(goal+8),vc_number(576,100)) && st_close(load64(goal+16),vc_number(1570796327,1000000000)),"camera point was not transformed into the physical oracle frame");
    text="{\"totalSteps\":1,\"case\":{\"perception\":{\"frameId\":1,\"detections\":[]}},\"localization\":{\"pose\":[0,0,0]}}";state=pj_parse(text,pl_size(text));vc_require(!sx_camera_goal(state,pose,goal),"empty camera invented a detection");
    if argc>1 {text="{\"totalSteps\":2,\"case\":{\"perception\":{\"frameId\":1,\"detections\":[{\"targetM\":[1,0,0]}]}},\"localization\":{\"pose\":[0,0,0]}}";state=pj_parse(text,pl_size(text));sx_camera_goal(state,pose,goal);vc_require(0,"stale detection accepted");}
    pl_print(1,"Training-only coverage uses room bounds and fresh camera detections.\n");return 0;
}
