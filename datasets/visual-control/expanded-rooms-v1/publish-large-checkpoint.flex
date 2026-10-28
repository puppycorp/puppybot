// Freeze an intermediate large checkpoint for an explicitly exploratory screen.
import "../../../flex/control/workflow.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==7 || argc==8,"publish-large-checkpoint WEIGHTS DATA INITIAL OUTPUT EPOCH TARGETS [--mirror-augment]");
    vw_root=vc_absolute(".");vw_output=vc_absolute(load64(argv+32));vw_epochs=pl_integer(load64(argv+40),pl_size(load64(argv+40)));vc_require(!pl_bad_number && vw_epochs>=0 && vw_epochs<=10000,"invalid checkpoint epoch");
    vw_target_positions=vc_absolute(load64(argv+48));vw_target_heatmap=1;vw_heat_actor=1;vw_heat_stop_gradient=1;vw_categorical=1;vw_event_aux=1;vw_batch=2;vw_rate=100;vw_seed=197;vw_checkpoint_every=1;
    if argc==8 {vc_require(pl_equal(load64(argv+56),"--mirror-augment"),"unknown checkpoint option");vw_mirror_augment=1;}
    let weights=vc_absolute(load64(argv+8));vc_require(vw_memory_width(weights)==256,"intermediate checkpoint is not a large model");vc_mkdir(vw_output);return vw_publish(vw_output,weights,"Exploratory intermediate large-model checkpoint",vc_absolute(load64(argv+16)),vc_absolute(load64(argv+24)));
}
