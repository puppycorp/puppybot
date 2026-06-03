#![cfg_attr(feature = "esp32", no_std)]

extern crate alloc;

#[cfg(feature = "host")]
use embassy_executor as _;

pub mod protocol;
pub mod puppyarm;
pub mod stservo;
