import "../control/host.flex";
import "../control/physical-sensor-gate.flex";
fn main(argc, argv) {
    vc_init(argc, argv);
    vc_require(pc_sensor_ok(1, 1, 100, 100, -1, 1, 0, 1), "valid reset rejected");
    vc_require(pc_sensor_ok(1, 1, 110, 110, 100, 2, 10, 1), "valid drive frame rejected");
    vc_require(pc_sensor_ok(1, 1, 112, 112, 110, 6, 0, 1), "valid stopped handoff frame rejected");
    vc_require(!pc_sensor_ok(0, 1, 110, 110, 100, 2, 10, 1), "non-driving camera accepted");
    vc_require(!pc_sensor_ok(1, 0, 110, 110, 100, 2, 10, 1), "moving camera accepted");
    vc_require(!pc_sensor_ok(1, 1, 109, 110, 100, 2, 10, 1), "stale camera frame accepted");
    vc_require(!pc_sensor_ok(1, 1, 111, 111, 100, 2, 10, 1), "incorrect drive step count accepted");
    vc_require(!pc_sensor_ok(1, 1, 110, 110, 100, 2, 10, 0), "changed arm accepted");
    vc_require(!pc_sensor_ok(1, 1, 111, 111, 110, 6, 0, 1), "incomplete stop accepted");
    vc_require(!pc_sensor_ok(1, 1, 110, 110, -1, 2, 10, 1), "drive accepted as first frame");
    vc_require(pc_status_ok(1, 0, 0) && pc_status_ok(2, 0, 1) && pc_status_ok(3, 2, 7), "valid acknowledgments rejected");
    vc_require(pc_status_ok(6, 0, 2) && pc_status_ok(6, 1, 3) && pc_status_ok(7, 1, 4) && pc_status_ok(7, 2, 5), "valid handoff acknowledgments rejected");
    vc_require(!pc_status_ok(2, 1, 1) && !pc_status_ok(3, 0, 7) && !pc_status_ok(6, 1, 2), "invalid owner accepted");
    vc_require(pc_drive_ok(2, 1, 30, 30, 112, 500, 500), "valid policy drive rejected");
    vc_require(pc_drive_ok(2, 1, 0, 0, 90, 0, 79), "dead-zone drive rejected");
    vc_require(!pc_drive_ok(2, 1, 29, 30, 112, 500, 500), "wrong wheel command accepted");
    vc_require(!pc_drive_ok(2, 1, 30, 30, 111, 500, 500), "wrong steering command accepted");
    vc_require(pc_drive_ok(3, 7, 0, 0, 90, 0, 0) && !pc_drive_ok(3, 7, 0, 1, 90, 0, 0), "invalid stop acknowledgment accepted");
    vc_require(pc_drive_ok(6, 2, 0, 0, 90, 0, 0) && !pc_drive_ok(6, 2, 0, 0, 91, 0, 0), "invalid handoff stop accepted");
    vc_require(pc_drive_ok(6, 3, 0, 0, 90, 0, 0) && !pc_drive_ok(6, 3, 0, 1, 90, 0, 0), "moving successful handoff accepted");
    vc_require(pc_drive_ok(7, 5, 0, 0, 90, 0, 0) && !pc_drive_ok(7, 5, 1, 0, 90, 0, 0), "moving collector terminal accepted");
    pl_print(1, "Physical sensor freshness and pose gate checks passed.\n"); return 0;
}
