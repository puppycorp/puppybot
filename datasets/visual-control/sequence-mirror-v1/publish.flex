import "../../../flex/control/workflow.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==7,"publish WEIGHTS DATA INITIAL OUTPUT EPOCH MIRROR");vw_root=vc_absolute(".");vw_output=vc_absolute(load64(argv+32));vw_epochs=pl_integer(load64(argv+40),pl_size(load64(argv+40)));vc_require(!pl_bad_number && (vw_epochs==10 || vw_epochs==20),"invalid fixed experiment epoch");
    vw_mirror_augment=pl_integer(load64(argv+48),pl_size(load64(argv+48)));vc_require(!pl_bad_number && (vw_mirror_augment==0 || vw_mirror_augment==1),"invalid mirror experiment arm");vw_batch=2;vw_rate=100;vw_seed=107;vw_checkpoint_every=10;vc_mkdir(vw_output);
    return vw_publish(vw_output,vc_absolute(load64(argv+8)),"Matched continuation: complete-history reflection ablation",vc_absolute(load64(argv+16)),vc_absolute(load64(argv+24)));
}
