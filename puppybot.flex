// Long-running PC controller; defaults to ./puppybot.json and a fake bus.
import "src/host/launcher.flex";
fn main(argc, argv) { return pl_script_launcher(argc, argv, "src/scripts/run-runtime.sh"); }
