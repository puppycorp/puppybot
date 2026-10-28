import "../control/pose-supervision.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"pose-open-tests DATA TARGETS");
    let data=vd_map(vc_absolute(load64(argv+8)));let bytes=vc_size;let row_bytes=vd_row_bytes(data);
    vc_require(row_bytes,"invalid pose-open dataset");pt_pose_open(vc_absolute(load64(argv+16)),data,bytes,row_bytes);
    pl_print(1,"Memory pose targets and dataset masks passed validation.\n");return 0;
}
