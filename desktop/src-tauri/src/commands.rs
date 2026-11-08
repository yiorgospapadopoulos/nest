//! The commands the web UI calls (web/src/desktop/bridge.ts). Argument names are
//! snake_case exactly as written here, and every command rejects with a plain message.
//! `window.__TAURI__` is available (withGlobalTauri), so `core.invoke` and `event.listen`
//! need no npm package.
//!
//! | Command | Arguments | Returns |
//! |---|---|---|
//! | get_daemon | none | { base_url, token } |
//! | pty_spawn | { id, cwd?, cols, rows } | id |
//! | pty_write | { id, data } | null |
//! | pty_resize | { id, cols, rows } | null |
//! | pty_kill | { id } | null |
//! | open_browser_window | { url, title?, label? } (label: the pane's open window, which then shows url) | the window's label |
//! | pick_folder | none | the chosen folder's path, or null when cancelled |
//! | start_service | none | "started", or "not_installed" without a nest.service unit; main window only |
//! | daemon_problem | none | what the daemon's log says stops it, in words for the user, or null; main window only |
//! | app_version | none | this app's version; main window only |
//! | swap_app | { path } (untrusted: a release's app file in the data folder) | null, with nothing done in a dev build, after the first call of a launch, or when the same swap came back unchanged minutes ago; else Nest restarts from it; main window only |
//! | install_state | none | { updating: { from_version, to_version, started_at } or null, release_url, released }, read from the data folder while the daemon may be down; main window only |
//! | relaunch_app | { version } (the ready update's, whose app file is in the data folder) | false in a dev build; else true, after starting the helper that opens the new app once the daemon answers, and Nest quits; main window only |
//! | uninstall_nest | { delete_data } | null: starts the released install's `nest uninstall` in a session of its own and quits; main window only |
//! | notification_server | none | the desktop's notification service by name, or null when none answers; main window only |
//! | browser_back, browser_forward, browser_reload | { label } (a browser window's) | null; main window only |
//! | local_servers | none | [{ port, process }] of this user's localhost listeners, by port; main window only |
//! | open_external | { url } (http, https or mailto) | null; main window only |
//! | open_path | { path, reveal?, create? } (in the home folder; a folder unless reveal; create makes a missing folder first) | null; main window only |
//! | open_text_file | { path, root } (path untrusted: a regular file inside root, itself in the home folder) | null, in the default text editor, or shown in its folder without one; main window only |
//! | save_file | { suggested_name, data_base64 or text } | the saved path, or null when cancelled; main window only |
//! | stage_artifact | { html } | the address to give the artifact's frame as its src |
//! | release_artifact | { url } | null |
//! | notify | { title, body, chat?, sound? } | null; sound plays the system's message sound |
//! | window_control | { action: "minimize" or "toggle_maximize" or "close" or "start_drag" or "quit" } | null |
//! | is_maximized | none | whether the calling window is maximized |
//! | window_state | none | { minimized, visible } of the calling window; main window only |
//! | show_main | none | null |
//! | pill_update | { visible?, width?, height?, room? } | null; width by height takes clicks, room is the window's height |
//! | pill_pointer | none | [x, y] of the pointer in the pill window in logical px, or null outside it |
//! | get_settings | none | { keep_pill_on_top, start_at_login, disable_dmabuf_renderer } |
//! | set_settings | { keep_pill_on_top?, start_at_login?, disable_dmabuf_renderer? } | the same as get_settings |
//!
//! Terminals: the caller picks the id (letters, digits, - and _, at most 64), listens to
//! `pty://<id>` (payload: output as a string, UTF-8 decoded across reads) and
//! `pty://<id>/exit` (payload: { code }), then calls pty_spawn, so no output is missed.
//! cwd defaults to the home folder; data is text to type.
//!
//! "close" hides the main window (Nest stays in the tray) and closes any other window.
//! The pill page draws itself and asks for its size with pill_update; Nest keeps it
//! centred at the top of the primary monitor. keep_pill_on_top and
//! disable_dmabuf_renderer change how Nest starts on Wayland, so they apply fully after
//! a restart.
//!
//! Artifacts: stage_artifact keeps the page until its frame loads it, once (see
//! artifact.rs); release_artifact drops a page whose reader closed before that.
//!
//! `nest://browser-closed` (payload: the label) to the main window when a browser window
//! closes, by its close button or Ctrl+W.
//!
//! Events to the main window: `nest://new-chat` and `nest://open-settings` (tray menu);
//! `nest://open` (payload: { chat }) when a notification sent with a chat (a session id) is
//! clicked, after Nest is brought forward.
//! Events to the main window and the pill: `nest://maximized` (payload: true or false)
//! whenever the window is maximized or restored, however it happened (title bar
//! button, double click, keyboard, window manager); is_maximized gives the state at start.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State, WebviewWindow};
use tauri_plugin_autostart::ManagerExt;
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;

use crate::artifact::Artifacts;
use crate::pty::Ptys;
use crate::settings::{self, Settings};
use crate::window::{self, MAIN, PILL};
use crate::{after_update, app_swap, daemon, env, external, install, notification};

pub struct AppState {
    pub settings_path: PathBuf,
    pub settings: Mutex<Settings>,
    pub pill_size: Mutex<window::PillSize>,
    /// The last maximized state sent to each window (`nest://maximized`).
    pub maximized: Mutex<HashMap<String, bool>>,
    /// Whether GTK's scale follows the display's while Nest runs: Nest chose XWayland and
    /// the user set no scale of their own (window::follow_display_scale).
    pub follow_display: bool,
    /// The variables Nest set for itself, which a new app must work out again.
    pub own_vars: Vec<String>,
    /// Whether this launch already tried to swap to a new app.
    pub swap_tried: AtomicBool,
}

#[derive(Serialize)]
pub struct SettingsView {
    keep_pill_on_top: bool,
    start_at_login: bool,
    disable_dmabuf_renderer: bool,
}

#[derive(Clone, Serialize)]
struct PtyExit {
    code: u32,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WindowAction {
    Minimize,
    ToggleMaximize,
    Close,
    StartDrag,
    Quit,
}

fn message(error: impl std::fmt::Display) -> String {
    error.to_string()
}

#[tauri::command(rename_all = "snake_case")]
pub async fn get_daemon() -> Result<daemon::DaemonInfo, String> {
    tauri::async_runtime::spawn_blocking(|| daemon::locate(&env::process))
        .await
        .map_err(message)?
}

#[tauri::command(rename_all = "snake_case")]
pub async fn pty_spawn(
    window: WebviewWindow,
    ptys: State<'_, Ptys>,
    id: String,
    cwd: Option<String>,
    cols: u16,
    rows: u16,
) -> Result<String, String> {
    let cwd = match cwd.filter(|cwd| !cwd.is_empty()) {
        Some(cwd) => PathBuf::from(cwd),
        None => env::home(&env::process)?,
    };
    if !cwd.is_dir() {
        return Err(format!("No such folder: {}", cwd.display()));
    }
    let app = window.app_handle().clone();
    let label = window.label().to_owned();
    let output_event = format!("pty://{id}");
    let exit_event = format!("pty://{id}/exit");
    let (output_app, output_label) = (app.clone(), label.clone());
    ptys.spawn(
        &id,
        ptys.login_shell(&cwd),
        cols,
        rows,
        move |chunk| {
            let _ = output_app.emit_to(output_label.as_str(), &output_event, chunk);
        },
        move |code| {
            let _ = app.emit_to(label.as_str(), &exit_event, PtyExit { code });
        },
    )?;
    Ok(id)
}

#[tauri::command(rename_all = "snake_case")]
pub async fn pty_write(ptys: State<'_, Ptys>, id: String, data: String) -> Result<(), String> {
    ptys.write(&id, data.as_bytes())
}

#[tauri::command(rename_all = "snake_case")]
pub async fn pty_resize(
    ptys: State<'_, Ptys>,
    id: String,
    cols: u16,
    rows: u16,
) -> Result<(), String> {
    ptys.resize(&id, cols, rows)
}

#[tauri::command(rename_all = "snake_case")]
pub async fn pty_kill(ptys: State<'_, Ptys>, id: String) -> Result<(), String> {
    ptys.kill(&id)
}

/// Starts the daemon's user service (`systemctl --user start nest.service`): "started", or
/// "not_installed" when there is no such unit.
#[tauri::command(rename_all = "snake_case")]
pub async fn start_service() -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(crate::platform::start_service)
        .await
        .map_err(message)?
        .map(str::to_owned)
}

/// Why the daemon does not start, when its log says so; it is down, so nothing else can.
#[tauri::command(rename_all = "snake_case")]
pub async fn daemon_problem() -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(|| daemon::problem(&env::process))
        .await
        .map_err(message)
}

#[tauri::command(rename_all = "snake_case")]
pub async fn app_version(app: AppHandle) -> Result<String, String> {
    Ok(app.package_info().version.to_string())
}

/// Swaps this app for the release's file and restarts from it, once a launch, so an app that
/// cannot swap does not try on every reload. A dev build has nothing to swap.
#[tauri::command(rename_all = "snake_case")]
pub async fn swap_app(
    app: AppHandle,
    state: State<'_, AppState>,
    path: String,
) -> Result<(), String> {
    if state.swap_tried.swap(true, Ordering::SeqCst) {
        return Ok(());
    }
    let exe = std::env::current_exe().map_err(message)?;
    let Some(install) = app_swap::locate(&env::process, &exe) else {
        return Ok(());
    };
    let data = daemon::data_dir(&env::process)?;
    let file = app_swap::app_file(&path, &data)?;
    let version = app.package_info().version.to_string();
    if app_swap::swapped_lately(&data, &file, &version) {
        return Ok(());
    }
    let own_vars = state.own_vars.clone();
    tauri::async_runtime::spawn_blocking(move || {
        app_swap::note_swap(&data, &file, &version)?;
        app_swap::swap(&file, &install, &own_vars)
    })
    .await
    .map_err(message)??;
    app.exit(0);
    Ok(())
}

/// An update under way, the install's address and whether it is a release, from the data
/// folder: the daemon is down while it updates, so it cannot say.
#[tauri::command(rename_all = "snake_case")]
pub async fn install_state() -> Result<install::InstallState, String> {
    tauri::async_runtime::spawn_blocking(|| {
        daemon::data_dir(&env::process).map(|data| install::state(&env::process, &data))
    })
    .await
    .map_err(message)?
}

/// Relaunch to update with a new app: after the daemon was asked to relaunch, a helper
/// waits for it and opens the new app once, or the old one if the update went back, and
/// this app quits. A dev build has nothing to swap: false, and it stays.
#[tauri::command(rename_all = "snake_case")]
pub async fn relaunch_app(
    app: AppHandle,
    state: State<'_, AppState>,
    version: String,
) -> Result<bool, String> {
    let exe = std::env::current_exe().map_err(message)?;
    let Some(install) = app_swap::locate(&env::process, &exe) else {
        return Ok(false);
    };
    let data = daemon::data_dir(&env::process)?;
    let file = data.join("daemon").join(&version).join("app-file");
    app_swap::app_file(&file.to_string_lossy(), &data)?;
    // The helper swaps; this launch does not try as well.
    state.swap_tried.store(true, Ordering::SeqCst);
    after_update::start(&install, &version, &state.own_vars)?;
    app.exit(0);
    Ok(true)
}

/// Starts `nest uninstall`, with `--delete-data` when asked, so it outlives the app and the
/// service, then quits.
#[tauri::command(rename_all = "snake_case")]
pub async fn uninstall_nest(
    app: AppHandle,
    state: State<'_, AppState>,
    delete_data: bool,
) -> Result<(), String> {
    let data = daemon::data_dir(&env::process)?;
    install::uninstall(&data, delete_data, &state.own_vars)?;
    app.exit(0);
    Ok(())
}

/// What answers Nest's notifications on this desktop, for the bug report's answer.
#[tauri::command(rename_all = "snake_case")]
pub async fn notification_server() -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(crate::platform::notification_server)
        .await
        .map_err(message)
}

/// This user's servers on localhost, for the browser's Local servers menu; never the
/// daemon's own port.
#[tauri::command(rename_all = "snake_case")]
pub async fn local_servers() -> Result<Vec<crate::platform::LocalServer>, String> {
    let daemon_port = daemon::base_url(&env::process)
        .ok()
        .and_then(|url| url.parse::<tauri::Url>().ok())
        .and_then(|url| url.port_or_known_default())
        .unwrap_or(daemon::DEFAULT_PORT);
    tauri::async_runtime::spawn_blocking(move || crate::platform::local_servers(daemon_port))
        .await
        .map_err(message)
}

/// Back, forward and reload in a browser window. Its page gets no IPC, so the history is
/// moved by a script Nest runs there.
fn in_browser(app: &AppHandle, label: &str, script: &str) -> Result<(), String> {
    let browser = window::browser_window(app, label)?;
    browser.eval(script).map_err(message)?;
    // The page the pane acted on comes forward.
    crate::platform::activate(&browser);
    Ok(())
}

#[tauri::command(rename_all = "snake_case")]
pub async fn browser_back(app: AppHandle, label: String) -> Result<(), String> {
    in_browser(&app, &label, "history.back()")
}

#[tauri::command(rename_all = "snake_case")]
pub async fn browser_forward(app: AppHandle, label: String) -> Result<(), String> {
    in_browser(&app, &label, "history.forward()")
}

#[tauri::command(rename_all = "snake_case")]
pub async fn browser_reload(app: AppHandle, label: String) -> Result<(), String> {
    in_browser(&app, &label, "location.reload()")
}

/// A web or mail link in the system's browser or mail app, as on the Mac.
#[tauri::command(rename_all = "snake_case")]
pub async fn open_external(app: AppHandle, url: String) -> Result<(), String> {
    let url = external::external_url(&url)?;
    app.opener()
        .open_url(url.as_str(), None::<&str>)
        .map_err(message)
}

/// A folder in the file manager, or with `reveal` any item shown in its folder; only in
/// the user's home folder. With `create`, a folder not there yet is made first.
#[tauri::command(rename_all = "snake_case")]
pub async fn open_path(
    app: AppHandle,
    path: String,
    reveal: Option<bool>,
    create: Option<bool>,
) -> Result<(), String> {
    let home = env::home(&env::process)?;
    if create.unwrap_or(false) {
        external::make_folder_in_home(&path, &home)?;
    }
    let path = external::path_in_home(&path, &home)?;
    if reveal.unwrap_or(false) {
        return app.opener().reveal_item_in_dir(&path).map_err(message);
    }
    if !path.is_dir() {
        return Err(format!("Not a folder: {}", path.display()));
    }
    app.opener()
        .open_path(path.to_string_lossy(), None::<&str>)
        .map_err(message)
}

/// A file a message names, in the app that opens text, never run and never through the
/// generic opener, which would run a script. Without such an app it is shown in its folder.
#[tauri::command(rename_all = "snake_case")]
pub async fn open_text_file(app: AppHandle, path: String, root: String) -> Result<(), String> {
    let file = external::text_file_in(&path, &root, &env::home(&env::process)?)?;
    let target = file.clone();
    let opened =
        tauri::async_runtime::spawn_blocking(move || crate::platform::open_in_text_editor(&target))
            .await
            .map_err(message)??;
    if opened {
        Ok(())
    } else {
        app.opener().reveal_item_in_dir(&file).map_err(message)
    }
}

/// The save dialog over the calling window, then the file written where the user chose;
/// the saved path, or null when cancelled.
#[tauri::command(rename_all = "snake_case")]
pub async fn save_file(
    window: WebviewWindow,
    suggested_name: String,
    data_base64: Option<String>,
    text: Option<String>,
) -> Result<Option<String>, String> {
    use base64::Engine;
    let bytes = match (data_base64, text) {
        (Some(data), None) => base64::engine::general_purpose::STANDARD
            .decode(data.trim())
            .map_err(|error| format!("The file's data is not base64: {error}"))?,
        (None, Some(text)) => text.into_bytes(),
        _ => return Err("Give the file as data_base64 or as text".to_owned()),
    };
    crate::platform::activate_file_dialog(&window);
    let picked = window
        .dialog()
        .file()
        .set_parent(&window)
        .set_file_name(external::file_name(&suggested_name))
        .set_can_create_directories(true)
        .blocking_save_file();
    let Some(picked) = picked else {
        return Ok(None);
    };
    let path = picked.into_path().map_err(message)?;
    std::fs::write(&path, bytes)
        .map_err(|error| format!("Could not save {}: {error}", path.display()))?;
    Ok(Some(path.to_string_lossy().into_owned()))
}

/// The folder dialog, over the calling window, as the Mac's Add folder panel.
#[tauri::command(rename_all = "snake_case")]
pub async fn pick_folder(window: WebviewWindow) -> Result<Option<String>, String> {
    crate::platform::activate_file_dialog(&window);
    let picked = window
        .dialog()
        .file()
        .set_parent(&window)
        .set_title("Choose a folder to open as a project")
        .set_can_create_directories(true)
        .blocking_pick_folder();
    picked
        .map(|path| {
            path.into_path()
                .map(|path| path.to_string_lossy().into_owned())
                .map_err(message)
        })
        .transpose()
}

#[tauri::command(rename_all = "snake_case")]
pub async fn open_browser_window(
    app: AppHandle,
    url: String,
    title: Option<String>,
    label: Option<String>,
) -> Result<String, String> {
    // A pane keeps one window: its page goes there while it is open.
    if let Some(label) = label {
        if let Ok(browser) = window::browser_window(&app, &label) {
            return window::navigate_browser(&browser, &url).map(|()| label);
        }
    }
    window::open_browser(&app, &url, title.as_deref().unwrap_or_default())
}

#[tauri::command(rename_all = "snake_case")]
pub async fn stage_artifact(
    artifacts: State<'_, Artifacts>,
    html: String,
) -> Result<String, String> {
    Ok(artifacts.stage(html))
}

#[tauri::command(rename_all = "snake_case")]
pub async fn release_artifact(artifacts: State<'_, Artifacts>, url: String) -> Result<(), String> {
    artifacts.release(&url);
    Ok(())
}

#[tauri::command(rename_all = "snake_case")]
pub async fn notify(
    app: AppHandle,
    title: String,
    body: String,
    chat: Option<String>,
    sound: Option<bool>,
) -> Result<(), String> {
    notification::show(&app, &title, &body, chat, sound.unwrap_or(false))
}

#[tauri::command(rename_all = "snake_case")]
pub async fn window_control(window: WebviewWindow, action: WindowAction) -> Result<(), String> {
    match action {
        WindowAction::Minimize => window.minimize(),
        WindowAction::ToggleMaximize => match window.is_maximized() {
            Ok(true) => window.unmaximize(),
            Ok(false) => window.maximize(),
            Err(error) => Err(error),
        },
        WindowAction::Close if window.label() == MAIN => window.hide(),
        WindowAction::Close => window.close(),
        WindowAction::StartDrag => window.start_dragging(),
        WindowAction::Quit => {
            window.app_handle().exit(0);
            Ok(())
        }
    }
    .map_err(message)
}

#[derive(Serialize)]
pub struct WindowStateView {
    minimized: bool,
    visible: bool,
}

/// Whether the calling window is minimised and shown. A minimised X11 window can still
/// report focus, so the page cannot tell from focus alone.
#[tauri::command(rename_all = "snake_case")]
pub async fn window_state(window: WebviewWindow) -> Result<WindowStateView, String> {
    Ok(WindowStateView {
        minimized: window.is_minimized().map_err(message)?,
        visible: window.is_visible().map_err(message)?,
    })
}

#[tauri::command(rename_all = "snake_case")]
pub async fn is_maximized(window: WebviewWindow) -> Result<bool, String> {
    window.is_maximized().map_err(message)
}

#[tauri::command(rename_all = "snake_case")]
pub async fn show_main(app: AppHandle) -> Result<(), String> {
    window::show_main(&app);
    Ok(())
}

#[tauri::command(rename_all = "snake_case")]
pub async fn pill_update(
    app: AppHandle,
    state: State<'_, AppState>,
    visible: Option<bool>,
    width: Option<f64>,
    height: Option<f64>,
    room: Option<f64>,
) -> Result<(), String> {
    let pill = app
        .get_webview_window(PILL)
        .ok_or("The pill window is closed")?;
    let resized = width.is_some() || height.is_some() || room.is_some();
    let size = {
        let mut size = state.pill_size.lock().unwrap();
        *size = size.with(width, height, room);
        *size
    };
    let showing = visible == Some(true) && !pill.is_visible().unwrap_or(false);
    if showing {
        pill.show().map_err(message)?;
    }
    // Placed again once shown: a window manager may place a window its own way when it
    // maps it, but it honours a move of a window already shown.
    if resized || showing {
        window::place_pill(&pill, size).map_err(message)?;
    }
    if visible == Some(false) {
        pill.hide().map_err(message)?;
    }
    Ok(())
}

/// Where the window system has the pointer over the pill: the page's own pointer events
/// miss a leave now and then and repeat old moves, so the pill asks before it opens and
/// while it is open (web/src/desktop/pillHover.ts).
#[tauri::command(rename_all = "snake_case")]
pub async fn pill_pointer(app: AppHandle) -> Result<Option<(f64, f64)>, String> {
    let pill = app
        .get_webview_window(PILL)
        .ok_or("The pill window is closed")?;
    let cursor = pill.cursor_position().map_err(message)?;
    let origin = pill.inner_position().map_err(message)?;
    let size = pill.inner_size().map_err(message)?;
    let scale = pill.scale_factor().map_err(message)?;
    Ok(window::pointer_in(
        (cursor.x, cursor.y),
        (origin.x, origin.y),
        (size.width, size.height),
        scale,
    ))
}

fn settings_view(app: &AppHandle, settings: &Settings) -> SettingsView {
    SettingsView {
        keep_pill_on_top: settings.keep_pill_on_top,
        start_at_login: app.autolaunch().is_enabled().unwrap_or(false),
        disable_dmabuf_renderer: settings.disable_dmabuf_renderer,
    }
}

#[tauri::command(rename_all = "snake_case")]
pub async fn get_settings(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<SettingsView, String> {
    let settings = state.settings.lock().unwrap().clone();
    Ok(settings_view(&app, &settings))
}

#[tauri::command(rename_all = "snake_case")]
pub async fn set_settings(
    app: AppHandle,
    state: State<'_, AppState>,
    keep_pill_on_top: Option<bool>,
    start_at_login: Option<bool>,
    disable_dmabuf_renderer: Option<bool>,
) -> Result<SettingsView, String> {
    if let Some(enabled) = start_at_login {
        let autostart = app.autolaunch();
        if enabled {
            autostart.enable()
        } else {
            autostart.disable()
        }
        .map_err(|error| format!("Could not change start at login: {error}"))?;
    }
    let settings = {
        let mut settings = state.settings.lock().unwrap();
        let mut changed = settings.clone();
        if let Some(on_top) = keep_pill_on_top {
            changed.keep_pill_on_top = on_top;
        }
        if let Some(disable) = disable_dmabuf_renderer {
            changed.disable_dmabuf_renderer = disable;
        }
        if changed != *settings {
            settings::save(&state.settings_path, &changed)?;
            *settings = changed;
        }
        settings.clone()
    };
    if let Some(pill) = app.get_webview_window(PILL) {
        let _ = pill.set_always_on_top(settings.keep_pill_on_top);
    }
    Ok(settings_view(&app, &settings))
}
