import "../control/host.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2,"stream-test EXPECTED_MILLISECONDS");let expected=pl_integer(load64(argv+8),pl_size(load64(argv+8)));vc_require(!pl_bad_number && vc_io_timeout==expected,"local stream timeout differs");pl_print(1,"Local stream timeout configuration passed.\n");return 0;
}
