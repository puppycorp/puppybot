// Strict training rejects empty candidate splits; merging may preserve them.
import "../control/target-supervision.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==4,"empty-target-source DATA TARGETS strict|merge");let data=vd_map(vc_absolute(load64(argv+8)));let bytes=vc_size;let target=vc_absolute(load64(argv+16));let mode=load64(argv+24);
    if pl_equal(mode,"strict") {pt_target_open(target,data,bytes,56);}else {vc_require(pl_equal(mode,"merge"),"invalid empty target mode");pt_target_open_for_merge(target,data,bytes,56);}
    pl_print(1,"Target source accepted.\n");return 0;
}
