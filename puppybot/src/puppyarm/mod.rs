pub mod controller;
pub mod kinematics;
#[cfg(any(feature = "esp32", test))]
pub mod puppyarm;
pub mod servo_safety;
#[cfg(feature = "host")]
pub mod state_engine;
#[cfg(any(feature = "esp32", test))]
pub mod task;
#[cfg(all(test, feature = "host"))]
mod test;

#[cfg(feature = "esp32")]
pub use puppyarm::PuppyArm;
#[cfg(feature = "host")]
pub use state_engine::PuppyArm;
