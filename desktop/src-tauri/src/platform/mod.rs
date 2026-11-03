//! What differs per operating system: default folders, how the local device token is
//! read, and the display setup done before the window toolkit starts. Each system's
//! module offers the same functions.

#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "linux")]
pub use linux::*;

#[cfg(target_os = "windows")]
mod windows;
#[cfg(target_os = "windows")]
pub use windows::*;
