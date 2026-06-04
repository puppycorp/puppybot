#![no_std]

extern crate alloc;

#[cfg(test)]
use embassy_executor as _;

pub mod protocol;
pub mod puppyarm;
pub mod stservo;
pub mod utility;
