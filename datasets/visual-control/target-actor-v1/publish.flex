import "../../../flex/control/workflow.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==7,"publish WEIGHTS DATA INITIAL OUTPUT EPOCH TARGET_DIRECTORY");vw_root=vc_absolute(".");vw_output=vc_absolute(load64(argv+32));vw_epochs=pl_integer(load64(argv+40),pl_size(load64(argv+40)));vc_require(!pl_bad_number && (vw_epochs==0 || vw_epochs==1 || vw_epochs==5 || vw_epochs==10 || vw_epochs==20 || vw_epochs==40),"invalid heat actor epoch");vw_target_positions=vc_absolute(load64(argv+48));vw_target_heatmap=1;vw_heat_actor=1;vw_batch=2;vw_rate=100;vw_seed=197;vw_checkpoint_every=1;vc_mkdir(vw_output);return vw_publish(vw_output,vc_absolute(load64(argv+8)),"Learned spatial camera feature connection",vc_absolute(load64(argv+16)),vc_absolute(load64(argv+24)));
}
