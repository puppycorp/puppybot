import "../../datasets/visual-control/expanded-rooms-v1/pose-memory-math.flex";
fn main(argc,argv) {
    vc_init(argc,argv);let initial=alloc(24);let pose=alloc(24);let target=alloc(32);let predicted=alloc(16);let errors=alloc(32);let weights=alloc(4096);let bias=alloc(16);let hidden=alloc(1024);
    store64(initial,f64_from_i64(1));store64(initial+8,f64_from_i64(2));store64(initial+16,pb_radians(f64_from_i64(90)));store64(pose,f64_from_i64(1));store64(pose+8,f64_from_i64(3));store64(pose+16,pb_radians(f64_from_i64(180)));
    qp_relative_pose(initial,pose,target);vc_require(f64_lt(f64_magnitude(f64_sub(load64(target),vc_number(1,8))),vc_number(1,100000)) && f64_lt(f64_magnitude(load64(target+8)),vc_number(1,100000)) && f64_lt(f64_magnitude(f64_sub(load64(target+16),PB_ONE)),vc_number(1,100000)) && f64_lt(f64_magnitude(load64(target+24)),vc_number(1,100000)),"relative pose axes or heading differ");
    pb_put32(hidden,0x3f800000);pb_put32(weights,pb_f64_to_f32(vc_number(1,8)));pb_put32(weights+8,0x3f800000);qp_predict_pose(weights,bias,hidden,predicted);qp_errors(target,predicted,errors);
    vc_require(f64_lt(load64(errors),vc_number(1,100000)) && f64_lt(f64_magnitude(f64_sub(load64(errors+8),PB_ONE)),vc_number(1,100000)) && load64(errors+24) && f64_lt(load64(errors+16),vc_number(1,100000)),"pose readout or error calculation differs");
    pb_put32(predicted+8,0);pb_put32(predicted+12,0);qp_errors(target,predicted,errors);vc_require(!load64(errors+24),"zero heading vector was treated as an angle");
    pl_print(1,"Pose probe frame, readout and undefined-heading checks passed.\n");return 0;
}
