// Exercise large mapped dataset boundaries without reading sparse image data.
import "../control/dataset.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3 || argc==4,"dataset-limit DATA EXPECTED_MAGIC [COPY]");let data=vd_map(load64(argv+8));let bytes=vc_size;
    vc_require(bytes>=32 && load64(data)==load64(load64(argv+16)),"unexpected dataset magic");let episodes=load64(data+8);let fit=load64(data+16);let length=load64(data+24);
    vc_require(episodes>=2 && episodes<=vd_episode_limit(data) && fit>=1 && fit<episodes && length>=1 && length<=512 && bytes==32+episodes*length*21224,"invalid dataset dimensions");
    syscall(11,data,bytes,0,0,0,0);if argc==4 {vd_copy_file(load64(argv+8),load64(argv+24));}return 0;
}
