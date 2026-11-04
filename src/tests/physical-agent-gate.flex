import "../control/host.flex";
import "../sim/physical-agent-gate.flex";
fn main(argc, argv) {
    vc_init(argc, argv);
    vc_require(ps_physical_sequence(0, 1) && ps_physical_sequence(40, 41), "sequential requests rejected");
    vc_require(!ps_physical_sequence(3, 3) && !ps_physical_sequence(3, 2) && !ps_physical_sequence(3, 5), "replayed or skipped request accepted");
    vc_require(ps_physical_permit(0, 0, 1, 0, 0, 0, 4), "physical reset rejected");
    vc_require(!ps_physical_permit(0, 0, 1, 0, 0, 0, 3), "virtual reset accepted");
    vc_require(!ps_physical_permit(0, 0, 2, 0, 0, 10, 0), "drive before reset accepted");
    vc_require(!ps_physical_permit(1, 0, 1, 0, 0, 0, 4), "second reset accepted");
    vc_require(ps_physical_permit(1, 0, 2, -1000, 1000, 20, 0), "bounded drive rejected");
    vc_require(!ps_physical_permit(1, 0, 2, 1001, 0, 10, 0), "invalid steering accepted");
    vc_require(!ps_physical_permit(1, 0, 2, 0, -1001, 10, 0), "invalid speed accepted");
    vc_require(!ps_physical_permit(1, 0, 2, 0, 0, 0, 0), "zero tick drive accepted");
    vc_require(!ps_physical_permit(1, 0, 2, 0, 0, 21, 0), "unbounded drive accepted");
    vc_require(ps_physical_permit(1, 0, 6, 0, 0, 0, 0), "handoff rejected");
    vc_require(!ps_physical_permit(1, 1, 2, 0, 0, 10, 0), "drive during collector ownership accepted");
    vc_require(!ps_physical_permit(1, 1, 6, 0, 0, 0, 0), "second handoff accepted");
    vc_require(!ps_physical_permit(1, 0, 7, 0, 0, 10, 0), "collector tick before handoff accepted");
    vc_require(ps_physical_permit(1, 1, 7, 0, 0, 20, 0), "bounded collector tick rejected");
    vc_require(!ps_physical_permit(1, 1, 7, 0, 0, 21, 0), "unbounded collector tick accepted");
    vc_require(!ps_physical_permit(1, 2, 2, 0, 0, 10, 0), "terminal state accepted drive");
    vc_require(!ps_physical_permit(1, 2, 7, 0, 0, 10, 0), "terminal state accepted collector tick");
    vc_require(!ps_physical_permit(1, 0, 4, 0, 0, 0, 0) && !ps_physical_permit(1, 0, 5, 0, 0, 0, 0), "oracle or virtual placement accepted");
    vc_require(ps_physical_permit(1, 1, 3, 0, 0, 0, 0), "emergency stop rejected");
    pl_print(1, "Physical-agent request gate checks passed.\n"); return 0;
}
