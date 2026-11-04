// Experimental simulator-only visual suspicion; never establishes obstruction.
// Integer fixed thresholds approximate the earlier offline exploration and must
// be independently qualified before interpreting a real simulator result.
import "environment.flex";
global os_previous=0;
global os_hist=0;
global os_texture_hist=0;
global os_count=0;
global os_static_pairs=0;
global os_bad_texture=0;
global os_bad_frames=0;
global os_previous_tick=-1;

fn os_reset() {
    if !os_previous { os_previous=alloc(21168); os_hist=alloc(511*8); os_texture_hist=alloc(766*8); os_bad_frames=alloc(10); }
    os_count=0; os_static_pairs=0; os_bad_texture=0; os_previous_tick=-1; return 0;
}
// First histogram bin whose cumulative frequency exceeds the zero-based rank.
fn os_rank(hist,bins,rank) {
    let i=0; let sum=0;
    while i<bins { sum=sum+load64(hist+i*8); if sum>rank { return i; } i=i+1; }
    vc_require(0,"invalid visual histogram"); return 0;
}
fn os_textured(image) {
    pb_zero(os_texture_hist,766*8); let i=0;
    while i<7056 { let sum=load8(image+i)+load8(image+7056+i)+load8(image+14112+i); let slot=os_texture_hist+sum*8; store64(slot,load64(slot)+1); i=i+1; }
    // Linear-interpolated gray p90-p10; both ranks are half-integers.
    let high=os_rank(os_texture_hist,766,6349)+os_rank(os_texture_hist,766,6350);
    let low=os_rank(os_texture_hist,766,705)+os_rank(os_texture_hist,766,706);
    // Abstain on the exact 12-level boundary because the exploratory NumPy
    // implementation uses float32 grayscale and may round either way.
    return high-low>72;
}
fn os_same(previous,image) {
    let channel=0; let residual2=0;
    while channel<3 {
        pb_zero(os_hist,511*8); let offset=channel*7056; let i=0;
        while i<7056 { let delta=load8(image+offset+i)-load8(previous+offset+i)+255; let slot=os_hist+delta*8; store64(slot,load64(slot)+1); i=i+1; }
        let center=os_rank(os_hist,511,3527)+os_rank(os_hist,511,3528);
        i=0; while i<511 { residual2=residual2+pb_abs(i*2-center)*load64(os_hist+i*8); i=i+1; } channel=channel+1;
    }
    // Exact integer version of mean residual < 0.25 for 3*7056 bytes.
    return residual2*2<21168;
}
// Input is the current fresh image and the already acknowledged command for
// the interval ending at this frame. A return of 2 is visual suspicion only;
// 3 is a low-texture abstention. Zero is warmup or an ineligible window.
fn os_observe(image,tick,acknowledged_speed) {
    vc_require(image && tick>=0,"invalid simulator visual observation");
    let texture=os_textured(image);
    if !os_count { vc_copy(os_previous,image,21168); os_previous_tick=tick; os_count=1; os_bad_texture=!texture; store8(os_bad_frames,!texture); return 0; }
    if tick!=os_previous_tick+10 || (acknowledged_speed> -80 && acknowledged_speed<80) {
        vc_copy(os_previous,image,21168); os_previous_tick=tick; os_count=1; os_static_pairs=0; os_bad_texture=!texture; store8(os_bad_frames,!texture); return 0;
    }
    if !os_same(os_previous,image) { os_static_pairs=0; }
    else { os_static_pairs=os_static_pairs+1; }
    let slot=os_bad_frames+(os_count%10); if os_count>=10 { os_bad_texture=os_bad_texture-load8(slot); }
    store8(slot,!texture); os_bad_texture=os_bad_texture+!texture;
    vc_copy(os_previous,image,21168); os_previous_tick=tick; os_count=os_count+1;
    if os_count>=10 && os_bad_texture { return 3; }
    if os_static_pairs>=9 { return 2; }
    return 0;
}
