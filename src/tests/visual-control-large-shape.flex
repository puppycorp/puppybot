// The wider actor has a separate 256-value recurrent interface.
import "../ml/runtime.flex";
import "../../build/flex/pixel-control-categorical-heat-large-model.flex";
fn main(argc,argv) {
    pl_init();vp_require(argc==1 || argc==3,"large-shape-tests [WEIGHTS SHA]");vp_init(".",0,0);if argc==3 {vp_checkpoint_open(load64(argv+8),load64(argv+16));}else {vp_compile_only=1;}pup_build_model();
    vp_require(vp_rank(vp_input)==4 && vp_dim(vp_input,1)==3 && vp_dim(vp_input,2)==84 && vp_dim(vp_input,3)==84,"large model image shape differs");
    vp_require(load64(vp_nodes)>5 && vp_dim(vp_at(vp_nodes,0),1)==32 && vp_dim(vp_at(vp_nodes,0),2)==20 && vp_dim(vp_at(vp_nodes,2),1)==64 && vp_dim(vp_at(vp_nodes,2),2)==9 && vp_dim(vp_at(vp_nodes,4),1)==192 && vp_dim(vp_at(vp_nodes,4),2)==7,"large encoder shape differs");
    vp_require(load64(vp_outputs)==2 && vp_dim(vp_at(vp_outputs,0),1)==7 && vp_dim(vp_at(vp_outputs,1),1)==256,"large actor or memory shape differs");
    pl_print(1,"Experimental 3M-parameter policy graph shapes passed.\n");return 0;
}
