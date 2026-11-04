import "worker.flex";
fn vv_usage() {return pl_print(1,"Usage: puppybot-vision --model MODEL.json --image IMAGE.png|jpg\n       [--frame-bytes 48000..131072 (worker only)] [--backend auto|sass|cuda|hip|cpu] [--device N] [--kernel DIRECTORY] [--output JSON] [--raw-output FILE] [--input-tensor FILE]\n");}
fn main(argc,argv) {
    if !pl_init() {return 1;}let manifest=0;let image=0;let backend=-1;let kernel="build/flex/pup-kernels";let output=0;let raw=0;let tensor_path=0;let worker=0;let frame_bytes=48000;let i=1;
    if argc>1 && pl_equal(pb_vget(argv,1),"worker") {worker=1;i=2;}
    while i<argc {let key=pb_vget(argv,i);if pl_equal(key,"--help") {vv_usage();return 0;}if i+1>=argc {vv_usage();return 2;}let value=pb_vget(argv,i+1);
        if pl_equal(key,"--model") {manifest=value;}else if pl_equal(key,"--image") {image=value;}else if pl_equal(key,"--kernel") {kernel=value;}else if pl_equal(key,"--output") {output=value;}else if pl_equal(key,"--raw-output") {raw=value;}else if pl_equal(key,"--input-tensor") {tensor_path=value;}else if pl_equal(key,"--frame-bytes") {frame_bytes=pl_integer(value,pl_size(value));if pl_bad_number || frame_bytes<48000 || frame_bytes>131072 {vv_usage();return 2;}}else if pl_equal(key,"--device") {vp_ordinal=pl_integer(value,pl_size(value));if pl_bad_number || vp_ordinal<0 || vp_ordinal>15 {vv_usage();return 2;}}else if pl_equal(key,"--backend") {backend=vp_backend_parse(value);if backend== -2 {vv_usage();return 2;}}else {vv_usage();return 2;}i=i+2;
    }
    if worker && manifest {return vv_worker_frames(manifest,kernel,backend,frame_bytes);}if !manifest || !image {vv_usage();return 2;}vd_setup(manifest,kernel,backend);let rgb=vi_image(image);let b=alloc(32);let text=alloc(131072);pl_builder(b,text,131072);vp_require(vd_detect_rgb(rgb,vi_width,vi_height,0,0,b),"result exceeds output buffer");
    if tensor_path {vp_require(!pl_atomic_file(tensor_path,vd_input,load64(vp_input+8)*4),"cannot save input tensor");}if raw {vp_require(!pl_atomic_file(raw,vd_data,load64(vp_output+8)*4),"cannot save output tensor");}if output {vp_require(!pl_atomic_file(output,text,load64(b+8)),"cannot save detections");}pl_print(1,text);return 0;
}
