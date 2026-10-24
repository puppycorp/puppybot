// Long-running PC controller; defaults to ./puppybot.json and a fake bus.
import "flex/host/launcher.flex";
fn main(argc, argv) { return pl_native_launcher(argc, argv, "flex/runtime/main.flex", "build/flex/puppybot-runtime"); }
