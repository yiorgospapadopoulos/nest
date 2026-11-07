#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Some(code) = nest_desktop_lib::after_update_helper() {
        std::process::exit(code);
    }
    // Before anything starts GTK: the display backend is chosen from the environment.
    let prepared = nest_desktop_lib::prepare();
    nest_desktop_lib::run(prepared);
}
