import "../control/host.flex";
import "../control/action-weight.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(f64_eq(pt_control_weight(0,0,PB_ONE),0),"masked action received weight");
    vc_require(f64_eq(pt_control_weight(PB_ONE,0,0),f64_from_i64(5)),"stationary stop weight differs");
    vc_require(f64_eq(pt_control_weight(PB_ONE,0,PB_ONE),f64_from_i64(40)),"stopping transition weight differs");
    vc_require(f64_eq(pt_control_weight(PB_ONE,PB_ONE,PB_ONE),PB_ONE),"steady driving weight differs");
    vc_require(f64_eq(pt_control_weight(PB_ONE,PB_ONE,0),f64_from_i64(8)),"starting transition weight differs");
    vc_require(f64_eq(pt_control_weight(PB_ONE,vc_number(-1,1),PB_ONE),f64_from_i64(8)),"reversal weight differs");
    vc_require(f64_eq(pt_control_weight(PB_ONE,vc_number(2,10),0),PB_ONE),"transition threshold is not strict");
    pt_stop_weight=PB_ONE;vc_require(f64_eq(pt_control_weight(PB_ONE,0,0),PB_ONE),"unweighted stationary stop differs");vc_require(f64_eq(pt_control_weight(PB_ONE,0,PB_ONE),f64_from_i64(8)),"unweighted stop transition lost its transition weight");vc_require(f64_eq(pt_control_weight(PB_ONE,PB_ONE,0),f64_from_i64(8)),"unweighted stop setting changed forward transition weight");
    pl_print(1,"Native action weighting checks passed.\n");return 0;
}
