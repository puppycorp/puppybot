// CPU-only probe of the real collector's 20-action boundary accounting.
import "../control/chase.flex";
fn reset() {
    // The episode resets counters but deliberately reuses its ring buffers.
    pb_zero(ve_pose,24);
    ve_steps=0;vx_backforth=0;vx_backforth_marked=-1;vx_chain=0;vx_drive=0;vx_pingpong=0;vx_marked=-1;return 0;
}
fn alternate(action,n) {
    let i=0;while i<n {pb_put32(action+4,0x3f800000);if i%2 {pb_put32(action+4,0xbf800000);}vx_track(action);ve_steps=ve_steps+1;i=i+1;}return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vx_trail=alloc(528);vx_turns=alloc(8);ve_pose=alloc(24);let action=alloc(8);pb_zero(action,8);pb_zero(vx_trail,528);pb_zero(vx_turns,8);
    reset();alternate(action,19);vx_track_backforth();vc_require(!vx_backforth,"incomplete window counted");
    reset();alternate(action,20);vc_require(!vx_backforth,"window counted before final pose");vx_track_backforth();vc_require(vx_backforth==20,"sole final window omitted");
    reset();alternate(action,22);vc_require(vx_backforth==21,"overlapping pre-final windows differ");vx_track_backforth();vc_require(vx_backforth==22,"final overlap counted incorrectly");
    reset();let i=0;while i<20 {pb_put32(action+4,0x3f800000);vx_track(action);ve_steps=ve_steps+1;i=i+1;}vx_track_backforth();vc_require(!vx_backforth,"stale previous episode drive signs counted");
    reset();alternate(action,20);store64(ve_pose,PB_ONE);vx_track_backforth();vc_require(!vx_backforth,"distant final pose counted");
    pl_print(1,"Back-and-forth final-window checks passed.\n");return 0;
}
