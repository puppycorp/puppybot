// Training-only coverage maps (collect --record-map, carried by the chase aggregator as map.bin): a readout of
// the memory learns which floor around the robot the camera has covered. 12x12 cells per row: 1 covered, 0 not
// yet, 2 no floor that could hold a brick (masked). The loss trains the readout and memory, never the actor.
import "dataset.flex";
global pt_map_data=0;
global pt_map_fit_loss=0;
global pt_map_fit_batches=0;
global pt_map_held_loss=0;
global pt_map_held_batches=0;
fn pt_map_open(path,data) {
    let n=load64(data+8);let fit=load64(data+16);let length=load64(data+24);pt_map_data=vc_map(path);let bytes=vc_size;
    vc_require(bytes==32+n*length*144 && load64(pt_map_data)==load64("PVMAP001") && load64(pt_map_data+8)==n && load64(pt_map_data+16)==fit && load64(pt_map_data+24)==length,"coverage map does not match the demonstration data");
    let i=32;while i<bytes {vc_require(load8(pt_map_data+i)<=2,"invalid coverage map cell");i=i+1;}return 0;
}
// A mirrored image swaps left and right, so each map row reverses.
fn pt_map_mirror(row) {
    let r=0;while r<12 {let c=0;while c<6 {let a=load8(row+r*12+c);store8(row+r*12+c,load8(row+r*12+11-c));store8(row+r*12+11-c,a);c=c+1;}r=r+1;}return 0;
}
fn pt_map_cells(row) {let count=0;let i=0;while i<144 {if load8(row+i)<2 {count=count+1;}i=i+1;}return count;}
fn pt_map_loss(prediction,row,weight,seed) {
    let loss=0;let i=0;while i<144 {let label=load8(row+i);
        if label<2 {let expected=0;if label {expected=PB_ONE;}loss=f64_add(loss,pt_binary_loss(pb_read_float(prediction+i*4),expected,weight,seed+i*4));}else {pb_put32(seed+i*4,0);}i=i+1;}
    return loss;
}
fn pt_map_record(training,loss) {
    if training {pt_map_fit_loss=f64_add(pt_map_fit_loss,loss);pt_map_fit_batches=pt_map_fit_batches+1;}else {pt_map_held_loss=f64_add(pt_map_held_loss,loss);pt_map_held_batches=pt_map_held_batches+1;}return 0;
}
fn pt_map_log(builder) {
    pl_text(builder,",\"mapTrainingLoss\":");if pt_map_fit_batches {pl_float(builder,f64_div(pt_map_fit_loss,f64_from_i64(pt_map_fit_batches)));}else {pl_text(builder,"null");}
    pl_text(builder,",\"mapValidationLoss\":");if pt_map_held_batches {pl_float(builder,f64_div(pt_map_held_loss,f64_from_i64(pt_map_held_batches)));}else {pl_text(builder,"null");}
    pt_map_fit_loss=0;pt_map_fit_batches=0;pt_map_held_loss=0;pt_map_held_batches=0;return 0;
}
