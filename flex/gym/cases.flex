import "../host/json.flex";
import "../../build/flex/gym-sim-cases.flex";

fn gg_case_valid(name) { return pl_equal(name, "arm-reach") || pl_equal(name, "joint-stall") || gg_native_case(name); }
fn gg_cases(builder) {
    return pl_text(builder, gg_case_catalog());
}
