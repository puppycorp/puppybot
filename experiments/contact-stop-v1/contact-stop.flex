// Simulator-only sustained-contact stop detector. It does not command or
// acknowledge a stop and must not be used as a physical safety mechanism.
// State: consecutive contact-and-drive samples, latched reason, threshold.
// Reasons: 0 none, 1 sustained contact, 2 invalid or stale observation.
fn cs_init(state,threshold) {
    if !state || threshold<1 || threshold>300 {return 0;}
    store64(state,0);store64(state+8,0);store64(state+16,threshold);return 1;
}
fn cs_reason(state) {
    if !state {return 2;}return load64(state+8);
}
// valid must be 1 only for a fresh verified observation. Contact must be
// binary; left and right are the previous commanded wheel speeds in [-100,100].
// Return 0 to continue, 1 to stop and report. Reasons remain latched.
fn cs_observe(state,valid,contact,left,right) {
    if !state {return 1;}
    if load64(state+8) {return 1;}
    if valid!=1 || contact<0 || contact>1 || left< -100 || left>100 || right< -100 || right>100 {
        store64(state+8,2);return 1;
    }
    if !contact || (!left && !right) {store64(state,0);return 0;}
    let count=load64(state)+1;store64(state,count);
    if count>=load64(state+16) {store64(state+8,1);return 1;}
    return 0;
}
