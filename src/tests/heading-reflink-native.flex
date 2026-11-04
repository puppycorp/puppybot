// Copied beside the isolated transformed dataset.flex; CPU-only clone check.
import "dataset.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"expected source and new target");
    vd_copy_file(load64(argv+8),load64(argv+16));pl_print(1,"Dataset FICLONE probe passed.\n");return 0;
}
