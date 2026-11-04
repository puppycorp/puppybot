// CPU fixture for the real private actor and map-boundary writers.
import "actor-attestation.flex";
import "parent-boundary.flex";
import "observation.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"usage: parent-boundary-probe NEW_ACTOR NEW_MAP");
    vc_pixels_init();let image=alloc(21168);let feedback=alloc(28);let hidden=alloc(128*4);
    let input=alloc((21168+7+128)*4);let output=alloc((2+128)*4);let action=alloc(8);let label=alloc(8);let map=alloc(144);
    pb_zero(image,21168);pb_zero(feedback,28);pb_zero(hidden,128*4);pb_zero(output,(2+128)*4);pb_zero(action,8);pb_zero(label,8);pb_zero(map,144);
    let a=pa_open(load64(argv+8),7820010,2,21168,128);let b=prb_open(load64(argv+16),7820010,2);
    store8(image,42);store8(map,2);pb_put32(action+4,0x3f800000);pb_put32(label,0x3f19999a);pb_put32(label+4,0x3f800000);
    vc_policy_input_dimensions(image,feedback,hidden,input,0,21168,128);pb_copy(output,action,8);
    pa_record(a,0,2,495,image,input,output,action);prb_record(b,0,2,495,map,label);
    store8(image,99);store8(map+1,1);pb_put32(feedback+24,0x3f800000);pb_put32(action,0x3f19999a);pb_put32(label,0);
    vc_policy_input_dimensions(image,feedback,hidden,input,0,21168,128);pb_copy(output,action,8);
    pa_record(a,1,3,505,image,input,output,action);prb_record(b,1,3,505,map,label);
    pa_finish(a);prb_finish(b);return 0;
}
