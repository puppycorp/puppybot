import "../../flex/control/host.flex";
import "visual-stall.flex";
fn main(argc,argv) {
    vc_init(argc,argv);let s=alloc(48);let prior=alloc(8);let image=alloc(8);pb_zero(image,8);
    vc_require(!vs_init(s,prior,8,1) && vs_init(s,prior,8,5),"bad threshold accepted");
    vc_require(!vs_observe(s,image,8,1,100,0,0),"first frame stopped");
    vc_require(!vs_observe(s,image,8,1,110,60,60) && !vs_observe(s,image,8,1,120,60,60),"early visual stop");
    vc_require(!vs_observe(s,image,8,1,130,60,60) && vs_observe(s,image,8,1,140,60,60),"five frames not detected");
    vc_require(vs_reason(s)==1 && vs_observe(s,image,8,1,150,60,60),"reason did not latch");
    vs_init(s,prior,8,5);let i=0;while i<12 {store8(image,i);vc_require(!vs_observe(s,image,8,1,100+i*10,60,60),"noisy frames triggered");i=i+1;}
    vs_init(s,prior,8,5);pb_zero(image,8);vs_observe(s,image,8,1,100,0,0);vs_observe(s,image,8,1,110,60,60);
    vc_require(!vs_observe(s,image,8,1,120,0,0) && load64(s)==1,"zero command did not reset");
    vc_require(!vs_observe(s,image,8,1,150,60,60) && load64(s)==1,"time gap did not reset");
    vc_require(vs_observe(s,image,8,1,150,60,60) && vs_reason(s)==2,"stale tick accepted");
    vs_init(s,prior,8,5);vc_require(vs_observe(s,image,8,0,100,0,0) && vs_reason(s)==2,"invalid camera accepted");
    vs_init(s,prior,8,5);vc_require(vs_observe(s,image,7,1,100,0,0) && vs_reason(s)==2,"wrong image size accepted");
    pl_print(1,"Exact visual-stall detector checks passed.\n");return 0;
}
