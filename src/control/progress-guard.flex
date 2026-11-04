// Progress guard for a fetch controller. It requests an external recovery;
// it never chooses motion or assumes that odometry proves progress. The caller
// must execute a safe bounded recovery, report its result, and stop the drive
// when the guard returns 3. This state machine is not wired into chase yet.
// State: last-clock, deadline-origin, attempts, mode, reason, idle limit,
// recovery deadline, attempt limit, last task progress, all i64 slots.
// Modes: 0 observing, 1 awaiting recovery result, 2 stopped.
// Reasons: 0 none, 1 invalid sensor, 2 attempts exhausted, 3 protocol error,
// 4 recovery timeout, 5 progress while recovery is unacknowledged. The caller
// must cancel any active motion on stop.
fn vg_init(state,now,idle,deadline,attempts) {
    if !state || now<0 || idle<1 || deadline<1 || attempts<1 {return 0;}
    store64(state,now);store64(state+8,now);store64(state+16,0);store64(state+24,0);store64(state+32,0);
    store64(state+40,idle);store64(state+48,deadline);store64(state+56,attempts);store64(state+64,now);return 1;
}
fn vg_stop(state,reason) {store64(state+24,2);store64(state+32,reason);return 3;}
// progress must mean a verified pickup or delivery, not wheel travel or a
// recovery completion. result: 0 pending/none, 1 completed, 2 failed. Both 1
// and 2 must acknowledge that recovery motion has stopped; an error alone is
// not such an acknowledgement. Invalid sensors must be reported immediately.
// Return: 0 observe, 1 start one recovery, 2 await its result, 3 stop/report.
fn vg_step(state,now,progress,sensor_ok,result) {
    if load64(state+24)==2 {return 3;}
    if now<load64(state) || progress<0 || progress>1 || sensor_ok<0 || sensor_ok>1 || result<0 || result>2 {return vg_stop(state,3);}
    store64(state,now);if !sensor_ok {return vg_stop(state,1);}
    if load64(state+24)==1 {
        if now-load64(state+8)>=load64(state+48) {return vg_stop(state,4);}
        if progress && !result {return vg_stop(state,5);}
        if progress {store64(state+8,now);store64(state+16,0);store64(state+24,0);store64(state+64,now);return 0;}
        if !result {return 2;}
        if result==2 && load64(state+16)>=load64(state+56) {return vg_stop(state,2);}
        store64(state+24,0);store64(state+8,now);return 0;
    }
    if result {return vg_stop(state,3);}
    if progress {store64(state+8,now);store64(state+16,0);store64(state+64,now);return 0;}
    if now-load64(state+8)<load64(state+40) {return 0;}
    // A completed recovery is not task progress. Give it one observation
    // interval, then stop rather than starting more than the allowed attempts.
    if load64(state+16)>=load64(state+56) {return vg_stop(state,2);}
    store64(state+16,load64(state+16)+1);store64(state+8,now);store64(state+24,1);return 1;
}
