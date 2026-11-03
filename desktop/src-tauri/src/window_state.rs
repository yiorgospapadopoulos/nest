//! Remembered window sizes across display scales. The window-state plugin saves sizes in
//! device pixels, so a size saved at 1x came back half as large at 2x (and twice as large
//! the other way). Nest records the scale the sizes are in and rescales them before the
//! plugin reads its file. Positions stay: they are on the same screen either way.

use std::path::Path;

use serde_json::Value;
use tauri::plugin::TauriPlugin;
use tauri::Wry;
use tauri_plugin_window_state::{StateFlags, DEFAULT_FILENAME};

use crate::window::{BROWSER_PREFIX, MAIN, PILL};

/// The scale the sizes in the plugin's file are in; a file without it was saved at 1x.
const SCALE_FILE: &str = ".window-state.scale";

fn flags() -> StateFlags {
    StateFlags::all().difference(StateFlags::VISIBLE)
}

pub fn plugin() -> TauriPlugin<Wry> {
    tauri_plugin_window_state::Builder::new()
        .with_denylist(&[PILL])
        // Browser windows are numbered afresh each run, so a saved one is another page's.
        .with_filter(|label| !label.starts_with(BROWSER_PREFIX))
        .with_state_flags(flags())
        .build()
}

/// Records the scale the sizes about to be saved are in: GTK's, which follows a display
/// scale change made while Nest runs.
fn record_scale(app: &tauri::AppHandle) {
    use tauri::Manager;
    let (Some(main), Ok(dir)) = (app.get_webview_window(MAIN), app.path().app_config_dir()) else {
        return;
    };
    if let Ok(scale) = main.scale_factor() {
        let _ = std::fs::write(dir.join(SCALE_FILE), scale.to_string());
    }
}

/// A move or resize settles this long before it is saved.
const SAVE_AFTER: std::time::Duration = std::time::Duration::from_secs(1);

/// Saves the windows' places soon after they stop moving: the plugin saves only when Nest
/// quits, so a Nest that was killed came back where it was before.
pub fn save_soon(app: &tauri::AppHandle) {
    use std::sync::Mutex;
    use std::time::Instant;
    use tauri_plugin_window_state::AppHandleExt;
    // When the last move came; Some while a saver waits.
    static LAST_MOVE: Mutex<Option<Instant>> = Mutex::new(None);
    let waiting = LAST_MOVE.lock().unwrap().replace(Instant::now()).is_some();
    if waiting {
        return;
    }
    let app = app.clone();
    std::thread::spawn(move || loop {
        std::thread::sleep(SAVE_AFTER);
        let settled = {
            let mut last = LAST_MOVE.lock().unwrap();
            let settled = last.is_none_or(|at| at.elapsed() >= SAVE_AFTER);
            if settled {
                *last = None;
            }
            settled
        };
        if settled {
            record_scale(&app);
            let _ = app.save_window_state(flags());
            return;
        }
    });
}

/// Where the window `label` was when Nest last quit (physical px), unless it was maximized.
/// The plugin moves a window there before it is first shown, which GNOME ignores, so Nest
/// moves it again once shown.
pub fn saved_position(dir: &Path, label: &str) -> Option<(i32, i32)> {
    let text = std::fs::read_to_string(dir.join(DEFAULT_FILENAME)).ok()?;
    let windows: Value = serde_json::from_str(&text).ok()?;
    let window = windows.get(label)?;
    if window.get("maximized").and_then(Value::as_bool) == Some(true) {
        return None;
    }
    let at = |key: &str| {
        window
            .get(key)?
            .as_i64()
            .and_then(|v| i32::try_from(v).ok())
    };
    Some((at("x")?, at("y")?))
}

/// Brings the saved sizes in `dir` to the `current` scale. Runs before the plugin loads.
pub fn adapt(dir: &Path, current: f64) {
    let saved = std::fs::read_to_string(dir.join(SCALE_FILE))
        .ok()
        .and_then(|text| text.trim().parse::<f64>().ok())
        .filter(|scale| *scale > 0.0)
        .unwrap_or(1.0);
    let state = dir.join(DEFAULT_FILENAME);
    if (saved - current).abs() > f64::EPSILON {
        if let Some(rescaled) = std::fs::read_to_string(&state)
            .ok()
            .and_then(|text| rescale(&text, current / saved))
        {
            let _ = std::fs::write(&state, rescaled);
        }
    }
    let _ = std::fs::create_dir_all(dir);
    let _ = std::fs::write(dir.join(SCALE_FILE), current.to_string());
}

/// The plugin's file with every window's width and height multiplied by `factor`.
fn rescale(text: &str, factor: f64) -> Option<String> {
    let mut windows: Value = serde_json::from_str(text).ok()?;
    for window in windows.as_object_mut()?.values_mut() {
        for key in ["width", "height"] {
            if let Some(size) = window.get(key).and_then(Value::as_u64) {
                let scaled = (size as f64 * factor).round().max(1.0) as u64;
                window[key] = Value::from(scaled);
            }
        }
    }
    serde_json::to_string(&windows).ok()
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;
    use crate::testing::TempDir;

    fn saved(dir: &Path, width: u32, height: u32) {
        let state = json!({ "main": {
            "width": width, "height": height, "x": 100, "y": 50, "prev_x": 100, "prev_y": 50,
            "maximized": false, "visible": true, "decorated": false, "fullscreen": false,
        }});
        std::fs::write(dir.join(DEFAULT_FILENAME), state.to_string()).unwrap();
    }

    fn main_window(dir: &Path) -> Value {
        let text = std::fs::read_to_string(dir.join(DEFAULT_FILENAME)).unwrap();
        serde_json::from_str::<Value>(&text).unwrap()["main"].clone()
    }

    #[test]
    fn a_size_saved_at_1x_comes_back_the_same_size_at_2x() {
        let dir = TempDir::new("window-state");
        // Saved by a version that did not record the scale, at 1x.
        saved(dir.path(), 1280, 820);

        adapt(dir.path(), 2.0);

        let main = main_window(dir.path());
        assert_eq!(
            (main["width"].clone(), main["height"].clone()),
            (json!(2560), json!(1640))
        );
        assert_eq!(
            (main["x"].clone(), main["y"].clone()),
            (json!(100), json!(50))
        );
        // Already at 2x now: another start at 2x leaves it.
        adapt(dir.path(), 2.0);
        assert_eq!(main_window(dir.path())["width"], json!(2560));
    }

    #[test]
    fn a_size_saved_at_2x_comes_back_the_same_size_at_1x() {
        let dir = TempDir::new("window-state");
        adapt(dir.path(), 2.0);
        // The plugin saves at exit, in the 2x pixels of that run.
        saved(dir.path(), 2560, 1640);

        adapt(dir.path(), 1.0);

        let main = main_window(dir.path());
        assert_eq!(
            (main["width"].clone(), main["height"].clone()),
            (json!(1280), json!(820))
        );
    }

    #[test]
    fn the_saved_position_comes_back_unless_the_window_was_maximized() {
        let dir = TempDir::new("window-state");
        assert_eq!(saved_position(dir.path(), "main"), None);
        saved(dir.path(), 1280, 820);
        assert_eq!(saved_position(dir.path(), "main"), Some((100, 50)));

        let maximized =
            json!({ "main": { "width": 1, "height": 1, "x": 0, "y": 0, "maximized": true } });
        std::fs::write(dir.path().join(DEFAULT_FILENAME), maximized.to_string()).unwrap();
        assert_eq!(saved_position(dir.path(), "main"), None);
    }

    #[test]
    fn nothing_saved_is_fine() {
        let dir = TempDir::new("window-state");

        adapt(dir.path(), 2.0);

        assert!(!dir.path().join(DEFAULT_FILENAME).exists());
    }
}
