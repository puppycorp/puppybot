import "../../../flex/control/workflow.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==6,"publish WEIGHTS DATA INITIAL OUTPUT EPOCH");vw_root=vc_absolute(".");vw_output=vc_absolute(load64(argv+32));vw_epochs=pl_integer(load64(argv+40),pl_size(load64(argv+40)));vc_require(!pl_bad_number && (vw_epochs==10 || vw_epochs==20),"invalid fixed pose experiment epoch");
    vw_batch=2;vw_rate=100;vw_seed=107;vw_checkpoint_every=10;vc_mkdir(vw_output);return vw_publish(vw_output,vc_absolute(load64(argv+8)),"Expanded physical starting-pose demonstrations",vc_absolute(load64(argv+16)),vc_absolute(load64(argv+24)));
}
