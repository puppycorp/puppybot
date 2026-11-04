// CPU-only probe compiled beside the isolated experimental detector.
import "sim-visual-stop.flex";
fn main(argc,argv) {
    vc_init(argc,argv);let image=alloc(21168);let i=0;
    while i<21168 { let x=i%84;let value=50;if (x/7)%2 {value=170;}store8(image+i,value);i=i+1; }
    os_reset();i=0;while i<9 {vc_require(!os_observe(image,i*10,200),"visual stop fired before ten frames");i=i+1;}
    vc_require(os_observe(image,90,200)==2,"textured static frames must flag suspicion");
    // A pattern moving by its period is indistinguishable from stillness.
    os_reset();i=0;while i<9 {vc_require(!os_observe(image,i*10,200),"periodic scene fired early");i=i+1;}
    vc_require(os_observe(image,90,200)==2,"periodic alias should expose ambiguous visual flag");
    os_reset();pb_zero(image,21168);i=0;while i<9 {vc_require(!os_observe(image,i*10,200),"flat scene fired early");i=i+1;}
    vc_require(os_observe(image,90,200)==3,"flat scene must abstain");
    os_reset();i=0;while i<12 {vc_require(!os_observe(image,i*10,0),"zero command must not trigger");i=i+1;}
    os_reset();i=0;while i<9 {vc_require(!os_observe(image,i*10,-200),"reverse warmup fired early");i=i+1;}
    vc_require(os_observe(image,90,-200)==3,"low texture must abstain while reversing");
    os_reset();i=0;while i<9 {vc_require(!os_observe(image,i*10,200),"unexpected warmup");i=i+1;}
    vc_require(!os_observe(image,100,200),"missing tick must reset window");
    // p10/p90 straddle histogram boundaries: interpolated range is only 6,
    // though a naive nearest-rank calculation incorrectly reports 12.
    i=0;while i<7056 {let value=11;if i<706 {value=0;}else if i>=6350 {value=12;}
        store8(image+i,value);store8(image+7056+i,value);store8(image+14112+i,value);i=i+1;}
    os_reset();i=0;while i<9 {vc_require(!os_observe(image,i*10,200),"adversarial quantile fired early");i=i+1;}
    vc_require(os_observe(image,90,200)==3,"interpolated low texture must abstain");
    // Exact gray spread 12 can round below 12 in float32; abstain.
    i=0;while i<7056 {let red=26;if i>=3528 {red=62;}store8(image+i,red);store8(image+7056+i,0);store8(image+14112+i,0);i=i+1;}
    os_reset();i=0;while i<9 {vc_require(!os_observe(image,i*10,200),"exact boundary fired early");i=i+1;}
    vc_require(os_observe(image,90,200)==3,"exact texture boundary must abstain");
    pl_print(1,"Sim visual stop CPU probe passed.\n");return 0;
}
