// Package an experimental 128x128 checkpoint with its inference assets.
import "../../../flex/control/workflow.flex";
import "../../../flex/control/target-supervision.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==8,"publish-highres WEIGHTS DATA TARGETS INITIAL OUTPUT EPOCHS BATCH");vw_root=vc_absolute(".");let weights=vc_absolute(load64(argv+8));let data=vc_absolute(load64(argv+16));vw_target_positions=vc_absolute(load64(argv+24));let initial=vc_absolute(load64(argv+32));let output=vc_absolute(load64(argv+40));let epoch=load64(argv+48);vw_epochs=pl_integer(epoch,pl_size(epoch));vc_require(!pl_bad_number && vw_epochs>=0 && vw_epochs<=10000,"invalid epoch count");let batch=load64(argv+56);vw_batch=pl_integer(batch,pl_size(batch));vc_require(!pl_bad_number && vw_batch>=1 && vw_batch<=8,"invalid batch size");
    let source=vc_map_highres(data);let bytes=vc_size;pt_target_open_with_image(vw_target_positions,source,bytes,56,49152);ve_image_side=128;ve_image_bytes=49152;vw_categorical=1;vw_target_heatmap=1;vw_heat_actor=1;vw_heat_stop_gradient=1;vw_rate=100;vw_seed=197;vw_checkpoint_every=0;if vw_epochs>1 {vw_checkpoint_every=1;}vc_mkdir(output);vw_publish(output,weights,"experimental-128x128",data,initial);return 0;
}
