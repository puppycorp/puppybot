// Appended to a disposable copy of train.flex by test.py. The host loss body
// is unchanged except that its device execution, transfers and optimizer are
// removed. It is a CPU test of batch masks and direct output-loss seeds only.
fn main(argc,argv) {
    vc_init(argc,argv);
    pt_length=4; pt_batch=1; pt_image_bytes=4; pt_row_bytes=56;
    pt_record_size=pt_length*(pt_image_bytes+pt_row_bytes);
    pt_data=alloc(32+pt_record_size);
    let order=alloc(8); store64(order,0);
    let t=0; while t<pt_length {
        let row=pt_data+32+pt_length*pt_image_bytes+t*pt_row_bytes;
        store8(pt_data+32+t*pt_image_bytes,10+t);
        pb_put32(row,0x3f000000);pb_put32(row+20,0x3f800000);
        pb_put32(row+28,0x3f000000); pb_put32(row+32,0x3f800000);
        pb_put32(row+40,0); if t<2 {pb_put32(row+40,0x3f800000);}
        pb_put32(row+44,0x3f800000);
        t=t+1;
    }
    pt_check_rows(1);
    pt_memcpy=ffi_symbol(ffi_open("libc.so.6"),"memcpy");
    vc_require(pt_memcpy,"missing memcpy");
    pt_batch_images=alloc(16); pt_batch_proprio=alloc(4*28);
    pt_batch_targets=alloc(4*16); pt_batch_phase_masks=alloc(4*4);
    pt_action_width=2; pt_prediction=alloc(4*2*4); pt_phase_prediction=alloc(4*4);
    pt_action_seed=alloc(4*2*4); pt_phase_seed=alloc(4*4);
    pt_event_aux=1; pt_event_prediction=alloc(4*4); pt_event_seed=alloc(4*4);
    pt_batch_fill(order,0,1);
    t=0; while t<4 {
        vc_require(load8(pt_batch_images+t*4)==10+t,"valid image history changed");
        vc_require(pb_u32(pt_batch_proprio+t*28)==0x3f000000 && pb_u32(pt_batch_proprio+t*28+20)==0x3f800000,"valid feedback history changed");
        vc_require(pb_u32(pt_batch_phase_masks+t*4)==pb_u32(pt_batch_targets+t*16+12),"default phase mask differs");
        t=t+1;
    }
    let original=pt_loss_host(1,0);
    vc_require(f64_is_finite(original),"nonfinite loss");
    t=0; while t<4 {
        let action=pt_action_seed+t*8; let phase=pt_phase_seed+t*4; let event=pt_event_seed+t*4;
        if t<2 {vc_require(f64_magnitude(pb_read_float(action+4)) && f64_magnitude(pb_read_float(phase)),"supervised prefix has no seed");}
        else {vc_require(!f64_magnitude(pb_read_float(action)) && !f64_magnitude(pb_read_float(action+4)) && !f64_magnitude(pb_read_float(phase)) && !f64_magnitude(pb_read_float(event)),"masked suffix has direct output gradient");}
        t=t+1;
    }
    // Change masked targets without changing predictions; direct loss and
    // prefix seeds remain identical. This does not execute the recurrent net.
    let first_action=pb_u32(pt_action_seed+4); let first_phase=pb_u32(pt_phase_seed);
    t=2; while t<4 {let target=pt_batch_targets+t*16; pb_put32(target,0xbf800000);pb_put32(target+4,0xbf800000);pb_put32(target+8,0x3f800000);t=t+1;}
    let changed=pt_loss_host(1,0);
    vc_require(f64_eq(changed,original) && pb_u32(pt_action_seed+4)==first_action && pb_u32(pt_phase_seed)==first_phase,"masked suffix targets affected direct loss");
    // --phase-from-valid deliberately uses valid frames despite zero labels.
    pt_phase_from_valid=1;pt_batch_fill(order,0,1);pt_loss_host(1,0);
    vc_require(f64_magnitude(pb_read_float(pt_phase_seed+8)),"phase-from-valid did not supervise suffix");
    // Memory-pose auxiliary validity is independent of the action mask.
    pt_phase_from_valid=0;pt_pose_aux=1;pt_pose_data=alloc(32+4*20);
    pt_batch_pose=alloc(4*20);pt_pose_prediction=alloc(4*16);pt_pose_seed=alloc(4*16);
    t=0;while t<4 {pb_put32(pt_pose_data+32+t*20,0x3f800000);pb_put32(pt_pose_data+32+t*20+16,0x3f800000);t=t+1;}
    pt_batch_fill(order,0,1);pt_loss_host(1,0);
    vc_require(f64_magnitude(pb_read_float(pt_pose_seed+2*16)),"pose auxiliary did not supervise valid suffix");
    // Coverage-map and target-position auxiliaries have their own validity
    // masks and can also seed valid rows whose action label is suppressed.
    pt_pose_aux=0;pt_map_aux=1;pt_map_data=alloc(32+4*144);
    pt_batch_map=alloc(4*144);pt_map_prediction=alloc(4*144*4);pt_map_seed=alloc(4*144*4);
    pt_target_aux=1;pt_target_data=alloc(32+4*12);pt_batch_target_positions=alloc(4*12);
    pt_target_prediction=alloc(4*8);pt_target_seed=alloc(4*8);
    t=0;while t<4 {let cell=0;while cell<144 {store8(pt_map_data+32+t*144+cell,2);cell=cell+1;}
        store8(pt_map_data+32+t*144,1);pb_put32(pt_target_data+32+t*12,0x3f000000);pb_put32(pt_target_data+32+t*12+8,0x3f800000);t=t+1;}
    pt_batch_fill(order,0,1);pt_loss_host(1,0);
    vc_require(f64_magnitude(pb_read_float(pt_map_seed+2*144*4)),"map auxiliary did not supervise valid suffix");
    vc_require(f64_magnitude(pb_read_float(pt_target_seed+2*8)),"target auxiliary did not supervise valid suffix");
    // The categorical actor and adjacent-step reversal/phase penalties must
    // not write a gradient across a supervised-to-masked boundary either.
    pt_map_aux=0;pt_target_aux=0;pt_action_width=7;pt_phase_from_valid=0;
    pt_prediction=alloc(4*7*4);pt_action_seed=alloc(4*7*4);
    pt_reversal_milli=0;pt_reversal_scratch=alloc(112);pt_phase_consistency_milli=0;
    pb_put32(pt_phase_prediction,0xbf800000);pb_put32(pt_phase_prediction+4,0x3f800000);
    t=0;while t<4 {let row=pt_data+32+pt_length*pt_image_bytes+t*pt_row_bytes;
        pb_put32(row+28,0xbf19999a);pb_put32(row+32,0x3f800000);t=t+1;}
    pt_batch_fill(order,0,1);pt_loss_host(1,0);
    let no_reversal_seed=pb_u32(pt_action_seed);let no_consistency_seed=pb_u32(pt_phase_seed);
    pt_reversal_milli=1000;pt_phase_consistency_milli=1000;pt_loss_host(1,0);
    vc_require(pb_u32(pt_action_seed)!=no_reversal_seed,"reversal positive control did not change prefix seed");
    vc_require(pb_u32(pt_phase_seed)!=no_consistency_seed,"phase consistency positive control did not change prefix seed");
    t=2;while t<4 {let j=0;while j<7 {
        vc_require(!f64_magnitude(pb_read_float(pt_action_seed+(t*7+j)*4)),"categorical or reversal gradient reached masked suffix");j=j+1;}
        vc_require(!f64_magnitude(pb_read_float(pt_phase_seed+t*4)) && !f64_magnitude(pb_read_float(pt_event_seed+t*4)),"phase or event gradient reached masked suffix");t=t+1;}
    vc_require(f64_magnitude(pb_read_float(pt_action_seed)),"categorical prefix has no seed");
    pl_print(1,"Native trainer host mask and loss-seed probe passed.\n");return 0;
}
