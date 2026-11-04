// Copied beside the isolated transformed chase.flex; CPU-only action checks.
import "chase.flex";
fn main(argc,argv) {
    pl_init();let logits=alloc(28);pb_zero(logits,28);pb_put32(logits,0x3e800000);let action=alloc(8);
    vw_straight_after=70;vw_straight_bias=50;vx_place_step=0;vx_carrying=0;vx_bias_eligible=0;vx_bias_changed=0;
    ve_steps=69;vx_pick(logits,action);vc_require(pb_u32(action)==0xbf19999a && !vx_bias_eligible && !vx_bias_changed,"bias applied before window");
    ve_steps=70;vx_pick(logits,action);vc_require(!pb_u32(action) && vx_bias_eligible==1 && vx_bias_changed==1,"window did not change argmax");
    ve_steps=99;vx_pick(logits,action);vc_require(!pb_u32(action) && vx_bias_eligible==2 && vx_bias_changed==2,"window ended too early");
    ve_steps=100;vx_pick(logits,action);vc_require(pb_u32(action)==0xbf19999a && vx_bias_eligible==2 && vx_bias_changed==2,"window did not end");
    vx_carrying=1;ve_steps=70;vx_pick(logits,action);vc_require(pb_u32(action)==0xbf19999a && vx_bias_eligible==2 && vx_bias_changed==2,"bias applied while carrying");
    vx_carrying=0;vw_straight_after=1000;ve_steps=300;vx_pick(logits,action);vc_require(pb_u32(action)==0xbf19999a && vx_bias_eligible==2 && vx_bias_changed==2,"control threshold activated");
    pl_print(1,"Bounded bias CPU probe passed.\n");return 0;
}
