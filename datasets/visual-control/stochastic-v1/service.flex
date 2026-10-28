// Same native CNN/GRU and protocols; only the non-raw joint-action decoder varies.
import "../../../flex/control/infer-service.flex";
import "sampling.flex";
fn ps_run(argc,argv) {
    if !pl_init() || (argc!=5 && argc!=6) {return 2;}let raw=argc==6;if raw && !pl_equal(load64(argv+40),"--raw") {return 2;}
    let fd=pl_integer(load64(argv+32),pl_size(load64(argv+32)));if pl_bad_number || fd<3 {return 2;}
    vp_init(load64(argv+24),vp_backend_parse("cuda"),0);vp_checkpoint_open(load64(argv+8),load64(argv+16));pup_build_model();vp_check(device_synchronize());
    vp_require(load64(vp_inputs)==3 && load64(vp_outputs)==2,"sampling policy requires three inputs and two outputs");let input_size=0;let output_size=0;let i=0;
    while i<3 {input_size=input_size+load64(vp_at(vp_at(vp_inputs,i),1)+8)*4;i=i+1;}i=0;while i<2 {output_size=output_size+load64(vp_at(vp_outputs,i)+8)*4;i=i+1;}
    vp_require(input_size==(21168+7+128)*4 && load64(vp_at(vp_outputs,0)+8)==7 && load64(vp_at(vp_outputs,1)+8)==128,"unexpected sampling-policy dimensions");
    let input=alloc(input_size);let output=alloc(output_size);let decoded=alloc(520);let magic="VCPOL001";if raw {magic="VCPRAW01";}vp_require(!pl_write(fd,magic,8),"cannot announce sampling policy");
    while pc_read(fd,input,input_size) {
        let offset=0;i=0;while i<3 {let tensor=vp_at(vp_at(vp_inputs,i),1);let size=load64(tensor+8)*4;vp_check(device_upload_async(load64(tensor),input+offset,size,vp_stream));offset=offset+size;i=i+1;}
        vp_execute();offset=0;i=0;while i<2 {let tensor=vp_at(vp_outputs,i);vp_read_tensor(tensor,output+offset);offset=offset+load64(tensor+8)*4;i=i+1;}
        let response=output;let size=output_size;if !raw {ps_reset(input+(21168+7)*4);vp_require(ps_decode(output,decoded)>=0,"invalid categorical sampling output");pb_copy(decoded+8,output+28,512);response=decoded;size=520;}
        if pl_write(fd,response,size) {return 1;}
    }return 0;
}
