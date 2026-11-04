import "../../flex/control/host.flex";
import "contact-stop.flex";
fn main(argc,argv) {
    vc_init(argc,argv);let state=alloc(24);
    vc_require(!cs_init(0,3) && !cs_init(state,0) && !cs_init(state,301),"invalid initialization accepted");
    vc_require(cs_init(state,3) && !cs_reason(state),"guard init failed");
    vc_require(!cs_observe(state,1,1,60,60) && !cs_observe(state,1,1,60,60),"contact threshold fired early");
    vc_require(cs_observe(state,1,1,60,60) && cs_reason(state)==1,"sustained contact was not latched");
    vc_require(cs_observe(state,1,0,0,0) && cs_reason(state)==1,"contact stop was silently cleared");
    cs_init(state,3);vc_require(!cs_observe(state,1,1,-60,-60) && !cs_observe(state,1,0,-60,-60),"valid contact reset failed");
    vc_require(!cs_observe(state,1,1,-60,0) && !cs_observe(state,1,1,-60,0),"intermittent contact accumulated");
    vc_require(!cs_observe(state,1,1,0,0) && !load64(state),"stopped drive did not reset count");
    vc_require(!cs_observe(state,1,1,0,60) && !cs_observe(state,1,1,0,60) && cs_observe(state,1,1,0,60),"one wheel driving did not count");
    cs_init(state,3);vc_require(cs_observe(state,0,0,0,0) && cs_reason(state)==2,"stale observation did not stop");
    vc_require(cs_observe(state,1,1,60,60) && cs_reason(state)==2,"invalid observation reason changed");
    cs_init(state,3);vc_require(cs_observe(state,2,0,0,0) && cs_reason(state)==2,"invalid validity accepted");
    cs_init(state,3);vc_require(cs_observe(state,1,2,0,0) && cs_reason(state)==2,"invalid contact accepted");
    cs_init(state,3);vc_require(cs_observe(state,1,1,-101,0) && cs_reason(state)==2,"invalid wheel command accepted");
    cs_init(state,3);vc_require(cs_observe(state,1,1,0,101) && cs_reason(state)==2,"invalid wheel command accepted");
    vc_require(cs_observe(0,1,0,0,0) && cs_reason(0)==2,"missing state accepted");
    pl_print(1,"Sustained-contact guard checks passed.\n");return 0;
}
