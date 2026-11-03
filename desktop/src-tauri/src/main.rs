#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // Before anything starts GTK: the display backend is chosen from the environment.
    let prepared = nest_desktop_lib::prepare();
    nest_desktop_lib::run(prepared);
}
