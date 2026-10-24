// Shared physical-controller admission policy; no platform I/O or allocation.
import "system.flex";

fn pb_temperature_fault(system, now) {
    let robot = load64(system); let i = 0;
    while i < 4 {
        let joint = pb_joint(robot, i); let time = pb_vget(system, 12 + i);
        if !pb_j(joint, PB_J_TEMP_VALID) || time < 0 { return 1; }
        if now < time || now - time > 250 { return 2; }
        if pb_j(joint, PB_J_TEMP) > 80 { return 3; } i = i + 1;
    } return 0;
}
fn pb_temperature_reason(code) {
    if code == 1 { return "unavailable"; } if code == 2 { return "stale"; }
    if code == 3 { return "over_temperature"; } return "none";
}
fn pb_feedback_ready(system, now) {
    if pb_temperature_fault(system, now) { return 0; }
    let robot = load64(system); let i = 0;
    while i < 4 {
        let joint = pb_joint(robot, i); let time = pb_j(joint, PB_J_LAST_FEEDBACK);
        if !pb_j(joint, PB_J_ONLINE) || !pb_j(joint, PB_J_FEEDBACK) || now < time || now - time > 250 { return 0; }
        i = i + 1;
    } return 1;
}
// Monitor polls must not consume the wheel-mode retry window for the first
// enabled command. Require fresh mode acknowledgements after every enable.
fn pb_rearm_outputs(robot) {
    pb_as(robot, PB_A_INITIALIZED, 0); let i = 0;
    while i < 4 { store64(pb_wheel_ready(robot, i), 0); store64(pb_wheel_attempt(robot, i), -1); pb_js(pb_joint(robot, i), PB_J_SENT_VALID, 0); i = i + 1; }
    return 0;
}
