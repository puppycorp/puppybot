import "../../../flex/control/workflow.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==6,"publish WEIGHTS DATA INITIAL OUTPUT EPOCH");vw_root=vc_absolute(".");vw_output=vc_absolute(load64(argv+32));vw_epochs=pl_integer(load64(argv+40),pl_size(load64(argv+40)));vw_rate=100;vw_seed=89;vw_batch=2;vw_checkpoint_every=20;vc_mkdir(vw_output);
    vw_publish(vw_output,vc_absolute(load64(argv+8)),"Strict35cm long student recovery imitation; fixed optimizer snapshot",vc_absolute(load64(argv+16)),vc_absolute(load64(argv+24)));return 0;
}
