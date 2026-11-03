//! The app's own settings, kept as JSON in the app config folder. Start at login is not
//! kept here: the autostart entry itself is the setting.

use std::fs;
use std::path::Path;

use serde::{Deserialize, Serialize};

pub const FILE_NAME: &str = "settings.json";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    /// Keeps the pixie pill above other windows. On Wayland this runs Nest through
    /// XWayland, read at launch.
    pub keep_pill_on_top: bool,
    /// Sets WEBKIT_DISABLE_DMABUF_RENDERER at launch, for GPUs that draw a blank window.
    pub disable_dmabuf_renderer: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            keep_pill_on_top: true,
            disable_dmabuf_renderer: false,
        }
    }
}

/// The saved settings; defaults when the file is missing or unreadable.
pub fn load(path: &Path) -> Settings {
    fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

pub fn save(path: &Path, settings: &Settings) -> Result<(), String> {
    let fail = |error: std::io::Error| format!("could not save {}: {error}", path.display());
    if let Some(folder) = path.parent() {
        fs::create_dir_all(folder).map_err(fail)?;
    }
    let text = serde_json::to_string_pretty(settings).map_err(|error| error.to_string())?;
    // A rename replaces the file whole, so a crash never leaves half a file.
    let partial = path.with_extension("json.partial");
    fs::write(&partial, text).map_err(fail)?;
    fs::rename(&partial, path).map_err(fail)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::TempDir;

    #[test]
    fn saved_settings_come_back() {
        let dir = TempDir::new("settings");
        let path = dir.path().join("config").join(FILE_NAME);
        let changed = Settings {
            keep_pill_on_top: false,
            disable_dmabuf_renderer: true,
        };

        save(&path, &changed).unwrap();

        assert_eq!(load(&path), changed);
    }

    #[test]
    fn missing_or_broken_file_gives_defaults() {
        let dir = TempDir::new("settings");
        let path = dir.path().join(FILE_NAME);
        assert_eq!(load(&path), Settings::default());
        assert!(Settings::default().keep_pill_on_top);

        fs::write(&path, "{ not json").unwrap();
        assert_eq!(load(&path), Settings::default());
    }

    #[test]
    fn a_file_without_a_setting_keeps_its_default() {
        let dir = TempDir::new("settings");
        let path = dir.path().join(FILE_NAME);
        fs::write(&path, r#"{"disable_dmabuf_renderer": true}"#).unwrap();

        let settings = load(&path);

        assert!(settings.keep_pill_on_top);
        assert!(settings.disable_dmabuf_renderer);
    }
}
