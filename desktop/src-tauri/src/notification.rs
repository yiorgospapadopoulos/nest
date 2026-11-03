//! Notifications: a click on one that names a chat brings Nest forward on that chat.

use serde::Serialize;
use tauri::{AppHandle, Emitter};

use crate::platform::{self, OnClick};
use crate::window::{self, MAIN};

/// Sent to the main window when a notification of a chat is clicked.
pub const OPEN_EVENT: &str = "nest://open";

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct OpenChat {
    pub chat: String,
}

pub fn show(
    app: &AppHandle,
    title: &str,
    body: &str,
    chat: Option<String>,
    sound: bool,
) -> Result<(), String> {
    platform::notify(title, body, sound, open_chat(app, chat))
}

/// The click action for a notification of `chat`; none without one. The notification
/// service calls it on a thread of its own.
fn open_chat(app: &AppHandle, chat: Option<String>) -> Option<OnClick> {
    let open = OpenChat {
        chat: chat.filter(|chat| !chat.is_empty())?,
    };
    let app = app.clone();
    Some(Box::new(move || {
        window::show_main(&app);
        let _ = app.emit_to(MAIN, OPEN_EVENT, open);
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_open_event_carries_the_chat() {
        let open = OpenChat {
            chat: "s-42".to_owned(),
        };

        assert_eq!(
            serde_json::to_value(open).unwrap(),
            serde_json::json!({ "chat": "s-42" })
        );
    }
}
