import "../../../flex/control/workflow.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==7,"publish WEIGHTS DATA INITIAL OUTPUT EPOCH ARM");vw_root=vc_absolute(".");vw_output=vc_absolute(load64(argv+32));vw_epochs=pl_integer(load64(argv+40),pl_size(load64(argv+40)));vc_require(!pl_bad_number && (vw_epochs==10 || vw_epochs==20),"invalid fixed later-search epoch");let arm=load64(argv+48);vc_require(pl_equal(arm,"baseline142") || pl_equal(arm,"late172"),"invalid later-search arm");
    vw_batch=2;vw_rate=100;vw_seed=149;vw_checkpoint_every=10;vc_mkdir(vw_output);return vw_publish(vw_output,vc_absolute(load64(argv+8)),vc_concat("Later-search correction ablation: ",arm),vc_absolute(load64(argv+16)),vc_absolute(load64(argv+24)));
}
