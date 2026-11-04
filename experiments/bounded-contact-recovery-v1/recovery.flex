// Isolated recovery contract; this state machine never sends drive commands.
// The caller must supply fresh observations and execute every stop request.
// Slots 0..64 are progress-guard state; +72 phase, +80 blocked sign,
// +88 recovery-contact, +96 local failure reason. All times are caller ticks.
// Return 1 stop/cancel, 2 ask policy for a proposal, 3 execute one proposal,
// 5 resume observation. Phase 6 is terminal and always returns 1.
// Local reasons: 1 bad protocol/sensor, 2 no verified clearance or unsafe
// proposal, 3 contact on recovery, 4 zero echo missing, 5 guard stopped.
fn rr_fail(state,reason) {
    store64(state+72,6);store64(state+96,reason);return 1;
}
fn rr_reason(state) {if !state {return 1;}return load64(state+96);}
fn rr_start(state,now,blocked_speed,deadline,observation) {
    if !state || now<1 || !blocked_speed || blocked_speed< -1000 || blocked_speed>1000 || deadline<2 || observation<1 {return 0;}
    if !vg_init(state,now-1,1,deadline,1) || vg_step(state,now,0,1,0)!=1 {return 0;}
    store64(state+40,observation);
    store64(state+72,1);let direction=1;if blocked_speed<0 {direction= -1;}
    store64(state+80,direction);store64(state+88,0);store64(state+96,0);return 1;
}
fn rr_pending(state,now,valid) {
    if !state {return 0;}
    if load64(state+72)==6 {return 0;}
    if valid!=1 {vg_step(state,now,0,0,0);rr_fail(state,1);return 0;}
    if vg_step(state,now,0,1,0)!=2 {rr_fail(state,5);return 0;}
    return 1;
}
// Caller has already requested zero and must supply a fresh zero echo.
fn rr_zero_before(state,now,valid,left,right) {
    if !state {return 1;}if load64(state+72)!=1 {return rr_fail(state,1);}
    if !rr_pending(state,now,valid) {return 1;}
    if left || right {return rr_fail(state,4);}store64(state+72,2);return 2;
}
// Accept a single bounded policy proposal only with separate, fresh,
// direction-specific clearance evidence. No wheel command or odometry is
// evidence of clearance. The caller must implement and validate that sensor.
fn rr_propose(state,now,valid,clear_fresh,clear_safe,speed,steering) {
    if !state {return 1;}if load64(state+72)!=2 {return rr_fail(state,1);}
    if !rr_pending(state,now,valid) {return 1;}
    if clear_fresh!=1 || clear_safe!=1 || !speed || speed< -250 || speed>250 ||
       steering< -500 || steering>500 || speed*load64(state+80)>=0 {return rr_fail(state,2);}
    store64(state+72,3);return 3;
}
// Exactly one corrective action is permitted; request zero immediately after
// its response even if contact is absent. The response is not task progress.
fn rr_after_action(state,now,valid,contact) {
    if !state {return 1;}if load64(state+72)!=3 {return rr_fail(state,1);}
    if !rr_pending(state,now,valid) {return 1;}
    if contact<0 || contact>1 {return rr_fail(state,1);}
    store64(state+88,contact);store64(state+72,4);return 1;
}
fn rr_zero_after(state,now,valid,left,right) {
    if !state {return 1;}if load64(state+72)!=4 {return rr_fail(state,1);}
    if !rr_pending(state,now,valid) {return 1;}
    if left || right {return rr_fail(state,4);}
    let contact=load64(state+88);let result=1;if contact {result=2;}
    let response=vg_step(state,now,0,1,result);
    if response==3 {if contact {return rr_fail(state,3);}return rr_fail(state,5);}
    if response {return rr_fail(state,1);}store64(state+72,5);return 5;
}
// A successful movement attempt does not reset the single-attempt budget.
// Only a separately verified pickup or delivery may reset the progress guard.
fn rr_observe(state,now,valid,verified_progress,stalled) {
    if !state {return 1;}if load64(state+72)==6 {return 1;}
    if load64(state+72)!=5 || valid!=1 || verified_progress<0 || verified_progress>1 || stalled<0 || stalled>1 {return rr_fail(state,1);}
    if vg_step(state,now,verified_progress,1,0)==3 {return rr_fail(state,5);}
    if stalled {return rr_fail(state,5);}return 5;
}
