// Cross-compilation check only; this is not flashable Puppybot firmware.
import "../core/system.flex";
import "../core/config.flex";
import "../vendor/esp32-xip.flex";

fn main() {
    let robot = alloc(8192); let system = alloc(2048);
    let frame = alloc(16); let response = alloc(256);
    if robot < 0 || system < 0 || frame < 0 || response < 0 { return 1; }
    let config = alloc(448); if config < 0 { return 1; }
    pb_config_default(config); if pb_robot_configure(robot, config, 0) { return 2; }
    pb_system_init(system, robot);
    store8(frame, 1); store8(frame + 1, 12); pb_put16(frame + 2, 2); pb_put16(frame + 4, 300);
    if pb_system_frame(system, frame, 6, response) < 0 { return 2; }
    if pb_system_begin(system, 20) <= 0 { return 3; }
    let n = pb_system_take_tx(system); if n != 8 { return 4; }
    pb_system_written(system, 20); pb_system_poll(system, 70);
    return 0;
}
