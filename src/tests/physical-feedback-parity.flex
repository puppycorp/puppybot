import "../control/physical-feedback.flex";
fn check(a, b, previous, original, actual) {
    let root = pj_parse(a, pl_size(a)); vc_require(root, "test JSON failed"); vc_feedback(root, previous, 0, original);
    let array = pj_parse(b, pl_size(b)); vc_require(array, "test array failed"); pc_feedback(array, previous, actual);
    let i = 0; while i < 7 { vc_require(pb_u32(original + i * 4) == pb_u32(actual + i * 4), "feedback bits differ from chase with zero contact and carry cue"); i = i + 1; }
    vc_require(!pb_u32(actual + 20) && !pb_u32(actual + 24), "diagnostic feedback is not zero");
    return 0;
}
fn main(argc, argv) {
    vc_init(argc, argv); let previous = alloc(8); let original = alloc(28); let actual = alloc(28);
    pb_put32(previous, 0x3e800000); pb_put32(previous + 4, 0xbf000000);
    check("{\"leftSpeed\":-60,\"rightSpeed\":35,\"steeringAngleDeg\":113}", "[-60,35,113]", previous, original, actual);
    check("{\"leftSpeed\":0,\"rightSpeed\":0,\"steeringAngleDeg\":90}", "[0,0,90]", previous, original, actual);
    check("{\"leftSpeed\":-100,\"rightSpeed\":100,\"steeringAngleDeg\":45}", "[-100,100,45]", previous, original, actual);
    check("{\"leftSpeed\":100,\"rightSpeed\":-100,\"steeringAngleDeg\":135}", "[100,-100,135]", previous, original, actual);
    pl_print(1, "Physical feedback matches zero-contact chase feedback.\n"); return 0;
}
