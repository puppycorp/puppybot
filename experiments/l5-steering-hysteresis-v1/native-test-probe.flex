// CPU-only disposable probe. It calls the transformed candidate directly.
import "chase.flex";
fn test_state(kind) {
    let text="{\"localization\":{\"mode\":\"wheel-drift\",\"source\":\"wheel-steering-command-integration\",\"pose\":[0,0,0]},\"step\":100,\"totalSteps\":100,\"camera\":{\"pose\":\"driving\",\"armSettled\":true},\"case\":{\"perception\":{\"frameId\":100}}}";
    if kind==1 {text="{\"localization\":{\"mode\":\"wheel-drift\",\"source\":\"wheel-steering-command-integration\",\"pose\":[0.149,0,0]},\"step\":100,\"totalSteps\":100,\"camera\":{\"pose\":\"driving\",\"armSettled\":true},\"case\":{\"perception\":{\"frameId\":100}}}";}
    if kind==2 {text="{\"localization\":{\"mode\":\"wheel-drift\",\"source\":\"wheel-steering-command-integration\",\"pose\":[0.15,0,0]},\"step\":100,\"totalSteps\":100,\"camera\":{\"pose\":\"driving\",\"armSettled\":true},\"case\":{\"perception\":{\"frameId\":100}}}";}
    if kind==3 {text="{\"localization\":{\"mode\":\"wheel-drift\",\"source\":\"wheel-steering-command-integration\",\"pose\":[0,0,0.8]},\"step\":100,\"totalSteps\":100,\"camera\":{\"pose\":\"driving\",\"armSettled\":true},\"case\":{\"perception\":{\"frameId\":100}}}";}
    if kind==4 {text="{\"localization\":{\"mode\":\"wheel-drift\",\"source\":\"wheel-steering-command-integration\",\"pose\":[0,0,0]},\"step\":100,\"totalSteps\":100,\"camera\":{\"pose\":\"driving\",\"armSettled\":true},\"case\":{\"perception\":{\"frameId\":99}}}";}
    if kind==5 {text="{\"localization\":{\"mode\":\"wheel-drift\",\"source\":\"wheel-steering-command-integration\",\"pose\":[0,0,0.7853981633974483]},\"step\":100,\"totalSteps\":100,\"camera\":{\"pose\":\"driving\",\"armSettled\":true},\"case\":{\"perception\":{\"frameId\":100}}}";}
    if kind==6 {text="{\"localization\":{\"mode\":\"wheel-drift\",\"source\":\"wheel-steering-command-integration\",\"pose\":[0,0,0.785]},\"step\":100,\"totalSteps\":100,\"camera\":{\"pose\":\"driving\",\"armSettled\":true},\"case\":{\"perception\":{\"frameId\":100}}}";}
    if kind==7 {text="{\"localization\":{\"mode\":\"truth\",\"source\":\"truth\",\"pose\":[0,0,0]},\"step\":100,\"totalSteps\":100,\"camera\":{\"pose\":\"driving\",\"armSettled\":true},\"case\":{\"perception\":{\"frameId\":100}}}";}
    ve_state=pj_parse(text,pl_size(text));vc_require(ve_state,"state parse failed");ve_last_step=100;return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"need case and fresh output directory");let mode=load64(argv+8);let directory=load64(argv+16);let action=alloc(8);
    vx_hys_begin(directory);vx_probe_trigger=1;vx_carrying=0;ve_contact=0;ve_steps=0;test_state(0);
    let i=0;while i<8 {
        if i==3 && pl_equal(mode,"carry-history") {vx_carrying=1;}
        if i==3 && pl_equal(mode,"contact-history") {ve_contact=1;}
        vx_hys_check();vc_require(!vx_hys_trigger,"activated before eight commands");
        pb_put32(action,0x3e800000);let bits=0x3f000000;if i%2 {bits=0xbf000000;}
        if i>=6 && pl_equal(mode,"five-flips") {bits=0xbf000000;}
        if i==7 && pl_equal(mode,"six-flips") {bits=0x3f000000;}
        if i==6 && pl_equal(mode,"zero-history") {bits=0;}
        if i==6 && pl_equal(mode,"negative-zero-history") {bits=0x80000000;}
        if i==6 && pl_equal(mode,"subnormal-history") {bits=1;}
        pb_put32(action+4,bits);vx_hys_apply(action);
        if i==7 && pl_equal(mode,"inside-distance") {test_state(1);}
        if i==7 && pl_equal(mode,"at-distance") {test_state(2);}
        if i==7 && pl_equal(mode,"turn") {test_state(3);}
        if i==7 && pl_equal(mode,"at-turn") {test_state(5);}
        if i==7 && pl_equal(mode,"inside-turn") {test_state(6);}
        vx_hys_observe(action);vx_carrying=0;ve_contact=0;ve_steps=ve_steps+1;i=i+1;
    }
    if pl_equal(mode,"stale") {test_state(4);}
    if pl_equal(mode,"truth-source") {test_state(7);}
    if pl_equal(mode,"no-kick") {vx_probe_trigger=0;}
    if pl_equal(mode,"current-contact") {ve_contact=1;}
    vx_hys_check();
    let blocked=pl_equal(mode,"five-flips") || pl_equal(mode,"zero-history") || pl_equal(mode,"negative-zero-history") || pl_equal(mode,"carry-history") || pl_equal(mode,"at-distance") || pl_equal(mode,"turn") || pl_equal(mode,"at-turn") || pl_equal(mode,"no-kick") || pl_equal(mode,"current-contact");
    if blocked {vc_require(!vx_hys_trigger && !vx_hys_used,"invalid gate activated");vx_hys_end();return 0;}
    let held=0xbf000000;let proposed=0x3f000000;let expected_sign=-1;
    if pl_equal(mode,"six-flips") {held=0x3f000000;proposed=0xbf000000;expected_sign=1;}
    vc_require(vx_hys_trigger && vx_hys_used && vx_hys_remaining==2 && vx_hys_sign==expected_sign,"expected activation");
    pb_put32(action,0x3e800000);pb_put32(action+4,proposed);if pl_equal(mode,"zero-action") {pb_put32(action+4,0);}
    vx_hys_apply(action);
    let expected=held;if pl_equal(mode,"zero-action") {expected=0;}
    vc_require(pb_u32(action)==0x3e800000 && pb_u32(action+4)==expected,"first hold failed");vx_hys_observe(action);ve_steps=ve_steps+1;
    if pl_equal(mode,"cancel-contact") {ve_contact=1;}
    if pl_equal(mode,"cancel-carry") {vx_carrying=1;}
    vx_hys_check();pb_put32(action+4,proposed);vx_hys_apply(action);
    if pl_equal(mode,"cancel-contact") || pl_equal(mode,"cancel-carry") {
        vc_require(pb_u32(action+4)==proposed && vx_hys_disabled,"active cancellation failed");
    } else {vc_require(pb_u32(action+4)==held,"second hold failed");}
    vx_hys_observe(action);ve_steps=ve_steps+1;ve_contact=0;vx_carrying=0;
    vx_hys_check();pb_put32(action+4,proposed);vx_hys_apply(action);
    vc_require(pb_u32(action+4)==proposed && !vx_hys_trigger,"third action modified or reactivated");
    vx_hys_end();return 0;
}
