// Exact actor-image suspicion detector; no commands or truth input. A matching
// image is not proof of stationary motion, a working camera or safe recovery.
// State: count, latched reason, threshold, previous image, size, prior tick.
// Reasons: 0 none, 1 repeated image, 2 invalid or stale observation.
fn vs_init(state,previous,size,threshold) {
    if !state || !previous || size<1 || size>1000000 || threshold<2 || threshold>300 {return 0;}
    store64(state,0);store64(state+8,0);store64(state+16,threshold);
    store64(state+24,previous);store64(state+32,size);store64(state+40,-1);return 1;
}
fn vs_reason(state) {if !state {return 2;}return load64(state+8);}
// Valid means frame ID and camera status were checked by the caller. One
// frame is counted only once. Reset across a time gap or a stopped command.
fn vs_observe(state,image,size,valid,tick,left,right) {
    if !state {return 1;}if load64(state+8) {return 1;}
    if !image || size!=load64(state+32) || valid!=1 || tick<0 || left< -100 || left>100 || right< -100 || right>100 {
        store64(state+8,2);return 1;
    }
    let previous_tick=load64(state+40);if previous_tick>=0 && tick<=previous_tick {store64(state+8,2);return 1;}
    let previous=load64(state+24);let same=1;let i=0;
    if previous_tick<0 {same=0;}else {while i<size && same {if load8(image+i)!=load8(previous+i) {same=0;}i=i+1;}}
    let count=1;
    if same && tick==previous_tick+10 && (left || right) {count=load64(state)+1;}
    vc_copy(previous,image,size);store64(state,count);store64(state+40,tick);
    if count>=load64(state+16) {store64(state+8,1);return 1;}
    return 0;
}
