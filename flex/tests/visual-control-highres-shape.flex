// The experimental 128x128 graph retains the existing recurrent interface.
import "../ml/runtime.flex";
import "../../build/flex/pixel-control-categorical-heat-128-model.flex";
fn main(argc,argv) {
    pl_init();vp_require(argc==1 || argc==3,"highres-shape-tests [WEIGHTS SHA]");vp_init(".",0,0);if argc==3 {vp_checkpoint_open(load64(argv+8),load64(argv+16));}else {vp_compile_only=1;}pup_build_model();
    vp_require(vp_rank(vp_input)==4 && vp_dim(vp_input,1)==3 && vp_dim(vp_input,2)==128 && vp_dim(vp_input,3)==128,"high-resolution image input shape differs");
    vp_require(load64(vp_nodes)>5 && vp_dim(vp_at(vp_nodes,0),2)==20 && vp_dim(vp_at(vp_nodes,0),3)==20 && vp_dim(vp_at(vp_nodes,2),2)==9 && vp_dim(vp_at(vp_nodes,4),2)==7,"high-resolution convolution shapes differ");
    vp_require(load64(vp_outputs)==2 && vp_dim(vp_at(vp_outputs,0),1)==7 && vp_dim(vp_at(vp_outputs,1),1)==128,"high-resolution actor or memory shape differs");
    pl_print(1,"Experimental 128x128 policy graph shape contracts passed.\n");return 0;
}
