// Every app command gets an `allow-<name>` permission, so a window can call only what
// its capability grants (capabilities/main.json); without a manifest any window could.
const COMMANDS: &[&str] = &[
    "get_daemon",
    "pty_spawn",
    "pty_write",
    "pty_resize",
    "pty_kill",
    "open_browser_window",
    "pick_folder",
    "start_service",
    "daemon_problem",
    "app_version",
    "swap_app",
    "browser_back",
    "browser_forward",
    "browser_reload",
    "local_servers",
    "open_external",
    "open_path",
    "open_text_file",
    "save_file",
    "stage_artifact",
    "release_artifact",
    "notify",
    "window_control",
    "is_maximized",
    "window_state",
    "show_main",
    "pill_update",
    "pill_pointer",
    "get_settings",
    "set_settings",
];

fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("failed to run tauri-build");
}
