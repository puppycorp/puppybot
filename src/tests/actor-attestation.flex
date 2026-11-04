// Isolated writer fixture. It does not hook or modify the active control path.
import "../control/actor-attestation.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2 || argc==3,"usage: actor-attestation-test NEW_FILE [bad-order]");
    let image=alloc(21168);let input=alloc((21168+7+128)*4);let output=alloc((2+128)*4);let action=alloc(8);
    pb_zero(image,21168);pb_zero(input,(21168+7+128)*4);pb_zero(output,(2+128)*4);pb_zero(action,8);
    let context=pa_open(load64(argv+8),1700000100,2,21168,128);
    pa_record(context,0,2,500,image,input,output,action);let index=1;if argc==3 {index=0;}pa_record(context,index,3,510,image,input,output,action);pa_finish(context);
    pl_print(1,"Actor attestation fixture written.\n");return 0;
}
