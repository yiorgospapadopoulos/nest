//! The tray icon. Linux trays (AppIndicator) report no clicks, so everything is in the menu.

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter};

use crate::window::{show_main, MAIN};

/// Sent to the main window when the tray menu asks for a new chat or for Settings.
pub const NEW_CHAT_EVENT: &str = "nest://new-chat";
pub const OPEN_SETTINGS_EVENT: &str = "nest://open-settings";

pub fn create(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "Open Nest", true, None::<&str>)?;
    let new_chat = MenuItem::with_id(app, "new-chat", "New chat", true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&open, &new_chat, &settings, &separator, &quit])?;

    let mut tray = TrayIconBuilder::with_id("nest")
        .tooltip("Nest")
        .menu(&menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => show_main(app),
            "new-chat" => {
                show_main(app);
                let _ = app.emit_to(MAIN, NEW_CHAT_EVENT, ());
            }
            "settings" => {
                show_main(app);
                let _ = app.emit_to(MAIN, OPEN_SETTINGS_EVENT, ());
            }
            "quit" => app.exit(0),
            _ => {}
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}
