//! The Windows layer, written in the Windows block. Until then a Windows build stops here.

compile_error!("Nest's Windows platform layer is not written yet (src/platform/windows.rs)");

use std::path::{Path, PathBuf};

use crate::env::Env;
use crate::settings::Settings;

pub fn default_data_dir(_env: Env, _home: &Path) -> PathBuf {
    unimplemented!()
}

pub fn default_config_dir(_env: Env, _home: &Path) -> PathBuf {
    unimplemented!()
}

pub fn app_config_dir(_env: Env, _home: &Path) -> PathBuf {
    unimplemented!()
}

pub fn activate(_window: &tauri::WebviewWindow) {
    unimplemented!()
}

pub type OnClick = Box<dyn FnOnce() + Send>;

pub fn notify(
    _title: &str,
    _body: &str,
    _sound: bool,
    _on_click: Option<OnClick>,
) -> Result<(), String> {
    unimplemented!()
}

pub fn never_focus(_window: &tauri::WebviewWindow) {
    unimplemented!()
}

pub fn close_on_ctrl_w(_window: &tauri::WebviewWindow) {
    unimplemented!()
}

/// A rectangle on screen in physical px.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Area {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

#[derive(Clone, Copy, Debug)]
pub struct Frame {
    /// The monitor the window is centred at the top of; None for the screen's origin.
    pub monitor: Option<Area>,
    /// From the monitor's top, logical px.
    pub top: i32,
    pub width: i32,
    pub height: i32,
    /// The size of what takes clicks, centred at the window's top.
    pub shape_width: i32,
    pub shape_height: i32,
    pub radius: f64,
}

pub fn place(_window: &tauri::WebviewWindow, _frame: Frame) {
    unimplemented!()
}

pub fn activate_file_dialog(_window: &tauri::WebviewWindow) {
    unimplemented!()
}

pub fn set_window_scale(_window: &tauri::WebviewWindow, _scale: i32) {
    unimplemented!()
}

pub fn on_monitors_changed(
    _window: &tauri::WebviewWindow,
    _changed: impl Fn() + Send + Sync + 'static,
) {
    unimplemented!()
}

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
pub struct LocalServer {
    pub port: u16,
    pub process: String,
}

pub fn local_servers(_skip_port: u16) -> Vec<LocalServer> {
    unimplemented!()
}

pub fn start_service() -> Result<&'static str, String> {
    unimplemented!()
}

pub fn open_in_text_editor(_file: &Path) -> Result<bool, String> {
    unimplemented!()
}

pub fn custom_scheme_url(_scheme: &str, _path: &str) -> String {
    unimplemented!()
}

pub fn read_local_token(_data_dir: &Path) -> Result<String, String> {
    unimplemented!()
}

pub struct DisplayScale;

pub fn read_display_scale(_log: &dyn Fn(String)) -> Option<DisplayScale> {
    unimplemented!()
}

pub fn display_env(
    _env: Env,
    _settings: &Settings,
    _scale: impl FnOnce() -> Option<DisplayScale>,
) -> Vec<(&'static str, String)> {
    unimplemented!()
}
