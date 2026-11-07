mod app_swap;
mod artifact;
mod commands;
mod daemon;
mod diagnostics;
mod env;
mod external;
mod notification;
mod platform;
mod pty;
mod settings;
#[cfg(test)]
mod testing;
mod tray;
mod window;
mod window_state;

use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::Mutex;

use tauri::{Emitter, Manager, WindowEvent};
use tauri_plugin_autostart::MacosLauncher;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

use crate::artifact::Artifacts;
use crate::commands::AppState;
use crate::pty::Ptys;
use crate::settings::Settings;

pub const IDENTIFIER: &str = "com.nest.desktop";
/// Passed by the login item, so Nest starts in the tray without opening its window.
const AUTOSTART_ARG: &str = "--autostart";

/// What the display setup depends on, logged with NEST_DEBUG_DISPLAY.
const DISPLAY_INPUTS: &[&str] = &[
    "WAYLAND_DISPLAY",
    "DISPLAY",
    "XDG_SESSION_TYPE",
    "GDK_BACKEND",
    "GDK_SCALE",
    "GDK_DPI_SCALE",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR",
    "GIO_LAUNCHED_DESKTOP_FILE",
];

/// What `prepare` found before the window toolkit started.
pub struct Prepared {
    settings_path: PathBuf,
    settings: Settings,
    set_vars: Vec<String>,
    follow_display: bool,
}

/// Reads the settings and sets the display variables GTK reads when it starts, so it
/// must run first thing in main.
pub fn prepare() -> Prepared {
    let env = env::process;
    let home = env::home(&env).expect("Nest needs HOME to find its settings");
    let settings_path = platform::app_config_dir(&env, &home).join(settings::FILE_NAME);
    let settings = settings::load(&settings_path);
    let seen: Vec<String> = DISPLAY_INPUTS
        .iter()
        .map(|name| format!("{name}={:?}", env::var(&env, name)))
        .collect();
    diagnostics::display(&format!(
        "start {:?}; {}; keep_pill_on_top={}",
        std::env::args().collect::<Vec<_>>(),
        seen.join(" "),
        settings.keep_pill_on_top
    ));
    let vars = platform::display_env(&env, &settings, || {
        platform::read_display_scale(&|line| diagnostics::display(&line))
    });
    diagnostics::display(&format!("display variables set: {vars:?}"));
    // Asked before Nest sets its own GDK_SCALE: a scale the user set stays.
    let follow_display = vars.iter().any(|(name, _)| *name == "GDK_BACKEND")
        && env::var(&env, "GDK_SCALE").is_none()
        && env::var(&env, "GDK_DPI_SCALE").is_none();
    for (name, value) in &vars {
        std::env::set_var(name, value);
    }
    Prepared {
        settings_path,
        settings,
        follow_display,
        set_vars: vars.iter().map(|(name, _)| (*name).to_owned()).collect(),
    }
}

fn open_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyN)
}

pub fn run(prepared: Prepared) {
    let pill_on_top = prepared.settings.keep_pill_on_top;
    let started_at_login = std::env::args().any(|arg| arg == AUTOSTART_ARG);
    let state = AppState {
        settings_path: prepared.settings_path,
        settings: Mutex::new(prepared.settings),
        pill_size: Mutex::new(window::PILL_SIZE),
        maximized: Mutex::default(),
        follow_display: prepared.follow_display,
        own_vars: prepared.set_vars.clone(),
        swap_tried: AtomicBool::new(false),
    };

    tauri::Builder::default()
        // First, so a second launch only brings the running Nest forward.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            window::show_main(app);
        }))
        // Its own commands are not granted to any window; pick_folder calls it from Rust.
        .plugin(tauri_plugin_dialog::init())
        // Like the dialog: only Nest's own commands (open_external, open_path) call it.
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec![AUTOSTART_ARG]),
        ))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        window::show_main(app);
                    }
                })
                .build(),
        )
        .manage(state)
        .manage(Ptys::new(prepared.set_vars))
        .manage(Artifacts::default())
        .register_uri_scheme_protocol(artifact::SCHEME, |context, request| {
            context
                .app_handle()
                .state::<Artifacts>()
                .serve(request.uri().path())
        })
        .setup(move |app| {
            let handle = app.handle();
            // Added here, once the display scale is known, so the saved sizes are first
            // brought to it.
            let scale = handle
                .primary_monitor()?
                .map_or(1.0, |monitor| monitor.scale_factor());
            let config_dir = handle.path().app_config_dir()?;
            window_state::adapt(&config_dir, scale);
            let saved_position = window_state::saved_position(&config_dir, window::MAIN);
            handle.plugin(window_state::plugin())?;
            let main = window::create_main(handle)?;
            diagnostics::display(&format!(
                "main window: scale {:?}, inner size {:?}, saved window state {:?}",
                main.scale_factor(),
                main.inner_size(),
                handle
                    .path()
                    .app_config_dir()
                    .map(|dir| std::fs::read_to_string(dir.join(".window-state.json")))
            ));
            if !started_at_login {
                main.show()?;
                main.set_focus()?;
            }
            // Where it was, once shown (GNOME places a new window itself), on screen.
            window::keep_main_on_screen(&main, saved_position, None)?;
            window::keep_main_placed(&main);
            window::create_pill(handle, pill_on_top)?;
            tray::create(handle)?;
            // Wayland without XWayland has no global shortcuts; Nest still runs.
            if let Err(error) = handle.global_shortcut().register(open_shortcut()) {
                eprintln!("nest: Ctrl+Alt+N is not available: {error}");
            }
            Ok(())
        })
        .on_window_event(|window, event| match event {
            WindowEvent::CloseRequested { api, .. } if window.label() == window::MAIN => {
                api.prevent_close();
                let _ = window.hide();
            }
            WindowEvent::Resized(_) => {
                window::report_maximized(window);
                if window.label() == window::MAIN {
                    window_state::save_soon(window.app_handle());
                }
            }
            WindowEvent::Destroyed if window.label().starts_with(window::BROWSER_PREFIX) => {
                let _ = window.app_handle().emit_to(
                    window::MAIN,
                    window::BROWSER_CLOSED_EVENT,
                    window.label(),
                );
            }
            WindowEvent::Moved(_) if window.label() == window::MAIN => {
                window_state::save_soon(window.app_handle());
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_daemon,
            commands::pty_spawn,
            commands::pty_write,
            commands::pty_resize,
            commands::pty_kill,
            commands::open_browser_window,
            commands::pick_folder,
            commands::start_service,
            commands::daemon_problem,
            commands::app_version,
            commands::swap_app,
            commands::browser_back,
            commands::browser_forward,
            commands::browser_reload,
            commands::local_servers,
            commands::open_external,
            commands::open_path,
            commands::open_text_file,
            commands::save_file,
            commands::stage_artifact,
            commands::release_artifact,
            commands::notify,
            commands::window_control,
            commands::is_maximized,
            commands::window_state,
            commands::show_main,
            commands::pill_update,
            commands::pill_pointer,
            commands::get_settings,
            commands::set_settings,
        ])
        .run(tauri::generate_context!())
        .expect("Nest could not start");
}
