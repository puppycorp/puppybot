// Standalone virtual STServo bus; connect Puppybot to the printed PTY path.
import "flex/host/launcher.flex";
fn main(argc, argv) { return pl_native_launcher(argc, argv, "flex/simulator/main.flex", "build/flex/puppybot-simulator"); }
