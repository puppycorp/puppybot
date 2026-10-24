import "../core/config.flex";
import "../../build/flex/esp32/config.flex";
fn main() { let config = alloc(448); return pf_physical_config(config); }
