import "../host/json.flex";

fn gg_case_valid(name) { return pl_equal(name, "arm-reach") || pl_equal(name, "joint-stall"); }
fn gg_cases(builder) {
    return pl_text(builder, "[{\"id\":\"arm-reach\",\"name\":\"Seeded joint targets\",\"backend\":\"servo-plant-v1\",\"description\":\"All four joints settle within 8 ticks for 25 steps.\"},{\"id\":\"joint-stall\",\"name\":\"Jammed yaw servo\",\"backend\":\"servo-plant-v1\",\"description\":\"Firmware reports stall and stops wheel outputs.\"}]");
}
