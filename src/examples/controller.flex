// Finite shared-controller demo. The fake servo feedback is illustrative;
// this executable does not model robot physics or connect to hardware.
import "../platform/fake.flex";

fn demo_print(text) { return syscall(1, 1, text, pb_text_size(text), 0, 0, 0); }
fn demo_number(value, scratch) {
    let at = 32; store8(scratch + at, 0);
    if !value { at = at - 1; store8(scratch + at, 48); }
    while value > 0 { at = at - 1; store8(scratch + at, 48 + value % 10); value = value / 10; }
    return demo_print(scratch + at);
}
fn demo_ticks(argc, argv) {
    if argc == 1 { return 120; } if argc != 2 { return -1; }
    let text = load64(argv + 8); let ticks = 0; let at = 0;
    while load8(text + at) {
        let c = load8(text + at); if c < 48 || c > 57 || ticks > 10000 { return -1; }
        ticks = ticks * 10 + c - 48; at = at + 1;
    }
    if !at || ticks < 1 || ticks > 100000 { return -1; } return ticks;
}
fn main(argc, argv) {
    let ticks = demo_ticks(argc, argv); if ticks < 0 { demo_print("Usage: controller-demo [ticks: 1..100000]\n"); return 2; }
    let robot = alloc(8192); let system = alloc(2048); let bus = alloc(16384);
    let values = alloc(40); let trace = alloc(1024); let scratch = alloc(64);
    if robot < 0 || system < 0 || bus < 0 || values < 0 || trace < 0 || scratch < 0 { return 3; }
    pb_robot_init(robot, 0); pb_system_init(system, robot); pb_fake_init(bus);
    pb_fake_servo(bus, 1, 2048); pb_fake_servo(bus, 2, 530); pb_fake_servo(bus, 3, 3565); pb_fake_servo(bus, 4, 1783); pb_fake_servo(bus, 5, 1535);
    pb_vset(values, 0, 5); pb_system_queue(system, 104, values);
    pb_vset(values, 0, 300); pb_system_queue(system, 1, values);
    pb_vset(values, 0, 0); pb_vset(values, 1, 1); pb_system_queue(system, 2, values);
    pb_vset(values, 0, 40); pb_vset(values, 1, 25); pb_system_queue(system, 101, values);
    let step = 0; let packets = 0; let hash = 0;
    while step < ticks {
        if step == 50 { pb_system_queue(system, 4, values); pb_system_queue(system, 103, values); }
        let n = pb_fake_cycle(system, bus, step * 20, trace, 1024); if n < 0 { return 4; }
        let at = 0; while at < n { let size = pb_u16(trace + at); packets = packets + 1; at = at + 2 + size; }
        at = 0; while at < n { hash = (hash * 31 + load8(trace + at)) & 0x7fffffff; at = at + 1; }
        let i = 1;
        while i <= 4 {
            let servo = bus + i * 48; let position = pb_vget(servo, 2) + pb_vget(servo, 3) * 20 / 1000;
            pb_vset(servo, 2, pb_canonical(position)); i = i + 1;
        }
        step = step + 1;
    }
    demo_print("{\"ticks\":"); demo_number(ticks, scratch);
    demo_print(",\"serialPackets\":"); demo_number(packets, scratch);
    demo_print(",\"traceChecksum\":"); demo_number(hash, scratch);
    demo_print(",\"armMode\":"); demo_number(pb_a(robot, PB_A_MODE), scratch);
    demo_print(",\"driveActive\":"); demo_number(pb_vget(pb_robot_drive(robot), 9), scratch);
    demo_print("}\n"); return 0;
}
