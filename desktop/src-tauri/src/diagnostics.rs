//! NEST_DEBUG_DISPLAY: how Nest set up its display, for when it looks wrong. Set to a file
//! path, lines are appended there (a launch from the app menu has no terminal); set to 1,
//! they go to stderr.

use std::io::Write;

pub const ENV: &str = "NEST_DEBUG_DISPLAY";

pub fn display(line: &str) {
    let Ok(target) = std::env::var(ENV) else {
        return;
    };
    let line = format!("nest[{}] {line}\n", std::process::id());
    if target == "1" {
        eprint!("{line}");
        return;
    }
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&target)
    {
        let _ = file.write_all(line.as_bytes());
    }
}
