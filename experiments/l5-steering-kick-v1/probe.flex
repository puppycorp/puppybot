// CPU-only checks, copied beside the isolated transformed chase.flex.
import "chase.flex";
fn main(argc,argv) {
    vc_init(argc,argv);let action=alloc(8);vx_probe_proposed=alloc(8);
    vw_steer_probe=2;vx_carrying=0;vx_probe_trigger=0;vx_probe_cancelled=0;ve_steps=0;
    pb_put32(action,0xbf19999a);pb_put32(action+4,0xbf800000);vx_probe_apply(action);
    vc_require(vx_probe_trigger && pb_u32(action)==0x3f19999a && pb_u32(action+4)==0xbf800000,"first kick or speed differs");
    ve_steps=1;pb_put32(action,0xbf19999a);vx_probe_apply(action);
    vc_require(pb_u32(action)==0x3f19999a,"second kick differs");
    ve_steps=2;vx_carrying=1;pb_put32(action,0xbf19999a);vx_probe_apply(action);
    vc_require(vx_probe_cancelled && pb_u32(action)==0xbf19999a,"carry cue did not cancel");
    vx_carrying=0;vx_probe_apply(action);vc_require(pb_u32(action)==0xbf19999a,"cancel was not latched");
    vx_probe_trigger=0;vx_probe_cancelled=0;ve_steps=0;vw_steer_probe=1;pb_put32(action,0xbf19999a);vx_probe_apply(action);
    vc_require(vx_probe_trigger && pb_u32(action)==0xbf19999a,"control action changed");
    vw_steer_probe=2;vx_probe_trigger=0;ve_steps=0;pb_put32(action,0x3f19999a);vx_probe_apply(action);
    vc_require(!vx_probe_trigger && pb_u32(action)==0x3f19999a,"positive steer triggered");
    vx_probe_trigger=0;ve_steps=0;pb_put32(action,0xbf19999a);pb_put32(action+4,0xbf000000);vx_probe_apply(action);
    vc_require(!vx_probe_trigger,"slow reverse triggered");
    vx_probe_trigger=1;ve_steps=3;pb_put32(action,0xbf19999a);pb_put32(action+4,0xbf800000);vx_probe_apply(action);
    vc_require(pb_u32(action)==0xbf19999a,"kick exceeded three actions");
    if argc>1 {
        let directory=load64(argv+8);let hidden=alloc(512);pb_zero(hidden,512);ve_memory_width=128;
        ve_image=alloc(21168);pb_zero(ve_image,21168);ve_image_bytes=21168;
        ve_feedback=alloc(28);pb_zero(ve_feedback,28);ve_previous=alloc(8);pb_zero(ve_previous,8);
        vx_carrying=0;vw_steer_probe=2;ve_steps=0;vx_probe_begin(directory);vx_probe_capture(hidden);
        pb_put32(action,0xbf19999a);pb_put32(action+4,0xbf800000);vx_probe_apply(action);
        vc_copy(ve_previous,action,8);ve_steering=600;ve_speed=-1000;ve_steps=1;
        let state="{\"controller\":{\"drive\":{\"leftSpeed\":-60,\"rightSpeed\":-60,\"steeringAngleDeg\":117}}}";
        ve_state=pj_parse(state,pl_size(state));vc_require(ve_state,"probe JSON failed");
        vx_probe_emit(action,hidden);vx_probe_end();
    }
    pl_print(1,"Steering probe CPU checks passed.\n");return 0;
}
