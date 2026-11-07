use std::io::{ErrorKind, Read};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::env::{var, Env};
use crate::settings::Settings;
use crate::IDENTIFIER;

/// The daemon serves this user's device token here, in its data folder (D075).
pub const TOKEN_SOCKET: &str = "token.sock";
const TOKEN_TIMEOUT: Duration = Duration::from_secs(5);

/// An XDG base directory; the spec says to ignore a relative one.
fn xdg_dir(env: Env, variable: &str, default: PathBuf) -> PathBuf {
    match var(env, variable) {
        Some(value) if Path::new(&value).is_absolute() => PathBuf::from(value),
        _ => default,
    }
}

/// Where the daemon keeps its data when NEST_DATA_DIR is not set (as the daemon decides).
pub fn default_data_dir(env: Env, home: &Path) -> PathBuf {
    xdg_dir(env, "XDG_DATA_HOME", home.join(".local").join("share")).join("nest")
}

/// The daemon's config folder (settings.toml) when NEST_CONFIG_DIR is not set.
pub fn default_config_dir(env: Env, home: &Path) -> PathBuf {
    xdg_dir(env, "XDG_CONFIG_HOME", home.join(".config")).join("nest")
}

/// This app's own config folder, the one Tauri's app_config_dir names.
pub fn app_config_dir(env: Env, home: &Path) -> PathBuf {
    xdg_dir(env, "XDG_CONFIG_HOME", home.join(".config")).join(IDENTIFIER)
}

/// Brings a window back, hidden or minimised, and focuses it, on the GTK main thread.
///
/// Mutter refuses a focus request with no time in it (what GTK's plain present sends) when
/// the user last did something in another window, and shows '"Nest" is ready' instead. The
/// shortcut, the tray menu and a second launch carry no time Nest can read, so the window
/// is presented with the X server's current time, which is never older than the user's
/// last action. Mutter also keeps a minimised X11 window mapped, where GTK's deiconify finds
/// nothing to do; hiding it and mapping it again is a restore Mutter honours.
pub fn activate(window: &tauri::WebviewWindow) {
    let target = window.clone();
    let _ = window.run_on_main_thread(move || {
        use gtk::prelude::*;
        let Ok(window) = target.gtk_window() else {
            return;
        };
        let shown = window.is_mapped();
        present(window.upcast_ref());
        if !shown {
            // Mutter drops an activation for a window it does not show yet ("not showing,
            // not focusing after all") and then maps it under the focused one, so a new
            // browser window seemed never to open. Asked again once it is up.
            let handler = std::rc::Rc::new(std::cell::Cell::new(None));
            let once = std::rc::Rc::clone(&handler);
            let id = window.connect_map_event(move |window, _| {
                if let Some(id) = once.take() {
                    window.disconnect(id);
                }
                let window = window.clone();
                gtk::glib::timeout_add_local_once(MAPPED_SETTLE, move || {
                    present(window.upcast_ref());
                });
                gtk::glib::Propagation::Proceed
            });
            handler.set(Some(id));
        }
    });
}

/// Brings the file dialog the dialog plugin is about to show forward and gives it the
/// keyboard. It presents the dialog without a user time, and Mutter left the keyboard on
/// Nest's window, so Ctrl+L and typing went there. Looked for on the GTK main thread a few
/// times, as the dialog comes up.
pub fn activate_file_dialog(window: &tauri::WebviewWindow) {
    let _ = window.run_on_main_thread(|| {
        let tries = std::rc::Rc::new(std::cell::Cell::new(0));
        gtk::glib::timeout_add_local(DIALOG_POLL, move || {
            use gtk::prelude::*;
            tries.set(tries.get() + 1);
            let dialog = gtk::Window::list_toplevels()
                .into_iter()
                .filter_map(|widget| widget.downcast::<gtk::Window>().ok())
                .find(|window| {
                    gtk::glib::prelude::ObjectExt::type_(window).name() == "GtkFileChooserDialog"
                        && window.is_visible()
                        && !window.is_active()
                });
            match dialog {
                Some(dialog) => {
                    present(&dialog);
                    gtk::glib::ControlFlow::Break
                }
                None if tries.get() >= DIALOG_TRIES => gtk::glib::ControlFlow::Break,
                None => gtk::glib::ControlFlow::Continue,
            }
        });
    });
}

const DIALOG_POLL: std::time::Duration = std::time::Duration::from_millis(100);
const DIALOG_TRIES: u32 = 30;

/// How long after a new window is mapped Mutter shows it.
const MAPPED_SETTLE: std::time::Duration = std::time::Duration::from_millis(150);

/// The work of `activate`, on the GTK main thread.
fn present(window: &gtk::Window) {
    use gtk::prelude::*;
    // A window just built has no X window yet to take a time from.
    if window.window().is_none() {
        window.realize();
    }
    let surface = window.window();
    let minimised = surface
        .as_ref()
        .is_some_and(|surface| surface.state().contains(gtk::gdk::WindowState::ICONIFIED));
    if minimised {
        window.hide();
        window.deiconify();
    }
    let surface = surface.and_then(|surface| surface.downcast::<gdkx11::X11Window>().ok());
    let time = match &surface {
        Some(surface) => {
            let time = gdkx11::functions::x11_get_server_time(surface);
            // Mutter judges a window being mapped by its user time, which GTK's present
            // leaves at the user's last click in Nest.
            surface.set_user_time(time);
            time
        }
        None => gtk::gdk::ffi::GDK_CURRENT_TIME as u32,
    };
    // A window built hidden (a new browser window) has its webview hidden too: present
    // would show the window alone, empty.
    if !window.is_visible() {
        window.show_all();
    }
    window.present_with_time(time);
    if let Some(surface) = &surface {
        activate_as_taskbar(surface, time);
    }
    // The page, not just the window, gets the keyboard, so typing goes where it was.
    focus_webview(window.upcast_ref());
}

/// Asks the window manager to activate the window as a taskbar does (EWMH source 2), which
/// Mutter always honours. A pill click came to a window that never takes the focus, and
/// Mutter refused GTK's own request (source 1) after it, restoring the window unfocused
/// with '"Nest" is ready' (B117 VM check). The pill, the tray and a second launch are
/// Nest's own taskbar, and only the user's action leads here.
fn activate_as_taskbar(surface: &gdkx11::X11Window, time: u32) {
    use gtk::prelude::*;
    use x11::xlib;
    let window: &gtk::gdk::Window = surface.upcast_ref();
    let Ok(display) = window.display().downcast::<gdkx11::X11Display>() else {
        return;
    };
    let atom = gdkx11::functions::x11_get_xatom_by_name_for_display(&display, "_NET_ACTIVE_WINDOW");
    // SAFETY: the display and window are GDK's, alive on this (the GTK main) thread, and
    // the event is a fully initialised client message sent to the root window.
    unsafe {
        let xdisplay = gdkx11::ffi::gdk_x11_display_get_xdisplay(display.as_ptr());
        let mut data = xlib::ClientMessageData::new();
        data.set_long(0, 2);
        data.set_long(1, std::ffi::c_long::from(time));
        let mut event = xlib::XEvent {
            client_message: xlib::XClientMessageEvent {
                type_: xlib::ClientMessage,
                serial: 0,
                send_event: xlib::True,
                display: xdisplay,
                window: surface.xid(),
                message_type: atom,
                format: 32,
                data,
            },
        };
        xlib::XSendEvent(
            xdisplay,
            xlib::XDefaultRootWindow(xdisplay),
            xlib::False,
            xlib::SubstructureRedirectMask | xlib::SubstructureNotifyMask,
            &mut event,
        );
        xlib::XFlush(xdisplay);
    }
}

/// Gives the keyboard focus to the first webview inside `widget`; whether there was one.
fn focus_webview(widget: &gtk::Widget) -> bool {
    use gtk::prelude::*;
    if widget.type_().name() == "WebKitWebView" {
        widget.grab_focus();
        return true;
    }
    widget
        .downcast_ref::<gtk::Container>()
        .is_some_and(|container| container.children().iter().any(focus_webview))
}

/// The pill's window: shown without ever taking the keyboard, even when clicked, and with
/// its presses for the page alone.
pub fn never_focus(window: &tauri::WebviewWindow) {
    let target = window.clone();
    let _ = window.run_on_main_thread(move || {
        use gtk::prelude::*;
        if let Ok(window) = target.gtk_window() {
            window.set_accept_focus(false);
            window.set_focus_on_map(false);
            // Not a normal window to Mutter: no focus on map, no place in the window list.
            window.set_type_hint(gtk::gdk::WindowTypeHint::Utility);
            // tao turns a press within 5 px (times the scale) of a resizable undecorated
            // window's edge into a resize, which ate clicks on the pill's edges, and shows a
            // resize cursor there. The page has every press and move first; none goes on to
            // the window.
            if let Some(webview) = find_webview(window.upcast_ref()) {
                for event in ["button-press-event", "motion-notify-event"] {
                    webview.connect_local(event, true, |_| Some(true.to_value()));
                }
            }
        }
    });
}

/// The first webview inside `widget`.
fn find_webview(widget: &gtk::Widget) -> Option<gtk::Widget> {
    use gtk::prelude::*;
    if widget.type_().name() == "WebKitWebView" {
        return Some(widget.clone());
    }
    widget
        .downcast_ref::<gtk::Container>()?
        .children()
        .iter()
        .find_map(find_webview)
}

/// Ctrl+W closes the window, as a browser window does on the Mac. Caught before the page
/// sees the key, so a page cannot keep its window open.
pub fn close_on_ctrl_w(window: &tauri::WebviewWindow) {
    let target = window.clone();
    let _ = window.run_on_main_thread(move || {
        use gtk::prelude::*;
        let Ok(gtk_window) = target.gtk_window() else {
            return;
        };
        gtk_window.connect_key_press_event(move |_, event| {
            let control = event.state().contains(gtk::gdk::ModifierType::CONTROL_MASK);
            let w = matches!(
                event.keyval(),
                gtk::gdk::keys::constants::w | gtk::gdk::keys::constants::W
            );
            if control && w {
                let _ = target.close();
                return gtk::glib::Propagation::Stop;
            }
            gtk::glib::Propagation::Proceed
        });
    });
}

/// What a click on a notification runs.
pub type OnClick = Box<dyn FnOnce() + Send>;

/// The freedesktop notification service, under Nest's name: GNOME labels a notification
/// from its desktop-entry hint (Nest.desktop, named after the product) and otherwise from
/// the sender's app name, which the notification plugin leaves at the binary's name.
const NOTIFICATIONS: (&str, &str, &str) = (
    "org.freedesktop.Notifications",
    "/org/freedesktop/Notifications",
    "org.freedesktop.Notifications",
);
const APP_NAME: &str = "Nest";
const DESKTOP_ENTRY: &str = "Nest";
const ICON: &str = "nest-desktop";
const MESSAGE_SOUND: &str = "message-new-instant";

pub fn notify(
    title: &str,
    body: &str,
    sound: bool,
    on_click: Option<OnClick>,
) -> Result<(), String> {
    static NOTIFIER: std::sync::OnceLock<Option<Notifier>> = std::sync::OnceLock::new();
    let notifier = NOTIFIER
        .get_or_init(Notifier::connect)
        .as_ref()
        .ok_or("Notifications are not available: no session bus")?;
    notifier.send(title, body, sound, on_click)
}

/// The desktop's notification service by its name; None when nothing answers, so Nest's
/// notifications would go nowhere.
pub fn notification_server() -> Option<String> {
    let connection = zbus::blocking::Connection::session().ok()?;
    let (name, path, interface) = NOTIFICATIONS;
    let reply = connection
        .call_method(
            Some(name),
            path,
            Some(interface),
            "GetServerInformation",
            &(),
        )
        .ok()?;
    let (server, _vendor, _version, _spec): (String, String, String, String) =
        reply.body().deserialize().ok()?;
    Some(server)
}

/// One connection for every notification: GNOME closes a notification once the connection
/// that sent it goes away, and some servers send its signals only to that connection.
struct Notifier {
    connection: zbus::blocking::Connection,
    clicks: std::sync::Arc<Clicks>,
}

impl Notifier {
    fn connect() -> Option<Self> {
        let (_, path, interface) = NOTIFICATIONS;
        let connection = zbus::blocking::Connection::session().ok()?;
        let rule = zbus::MatchRule::builder()
            .msg_type(zbus::message::Type::Signal)
            .path(path)
            .ok()?
            .interface(interface)
            .ok()?
            .build();
        let signals =
            zbus::blocking::MessageIterator::for_match_rule(rule, &connection, None).ok()?;
        let clicks = std::sync::Arc::new(Clicks::default());
        let listening = std::sync::Arc::clone(&clicks);
        std::thread::Builder::new()
            .name("notification-clicks".into())
            .spawn(move || {
                for signal in signals.flatten() {
                    let header = signal.header();
                    let body = signal.body();
                    match header.member().map(|member| member.as_str()) {
                        Some("ActionInvoked") => {
                            if let Ok((id, action)) = body.deserialize::<(u32, String)>() {
                                listening.invoked(id, &action);
                            }
                        }
                        Some("NotificationClosed") => {
                            if let Ok((id, _reason)) = body.deserialize::<(u32, u32)>() {
                                listening.closed(id);
                            }
                        }
                        _ => {}
                    }
                }
            })
            .ok()?;
        Some(Self { connection, clicks })
    }

    fn send(
        &self,
        title: &str,
        body: &str,
        sound: bool,
        on_click: Option<OnClick>,
    ) -> Result<(), String> {
        let (destination, path, interface) = NOTIFICATIONS;
        let actions: &[&str] = if on_click.is_some() {
            &["default", ""]
        } else {
            &[]
        };
        let mut hints = std::collections::HashMap::from([(
            "desktop-entry",
            zbus::zvariant::Value::from(DESKTOP_ENTRY),
        )]);
        if sound {
            // The freedesktop sound theme's name for an incoming message.
            hints.insert("sound-name", zbus::zvariant::Value::from(MESSAGE_SOUND));
        }
        // Held while the notification is sent, so a click that comes before its id is
        // recorded waits for it.
        let mut pending = self.clicks.pending.lock().unwrap();
        let id: u32 = self
            .connection
            .call_method(
                Some(destination),
                path,
                Some(interface),
                "Notify",
                &(APP_NAME, 0u32, ICON, title, body, actions, hints, -1i32),
            )
            .and_then(|reply| reply.body().deserialize())
            .map_err(|error| format!("Could not show the notification: {error}"))?;
        if let Some(on_click) = on_click {
            pending.insert(id, on_click);
        }
        Ok(())
    }
}

/// The click actions of the notifications still shown, by the server's id.
#[derive(Default)]
struct Clicks {
    pending: std::sync::Mutex<std::collections::HashMap<u32, OnClick>>,
}

impl Clicks {
    /// A click on the notification itself is its `default` action; it runs at most once.
    fn invoked(&self, id: u32, action: &str) {
        if action != "default" {
            return;
        }
        let on_click = self.pending.lock().unwrap().remove(&id);
        if let Some(on_click) = on_click {
            on_click();
        }
    }

    fn closed(&self, id: u32) {
        self.pending.lock().unwrap().remove(&id);
    }
}

/// A rectangle on screen in physical px.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Area {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

/// A window centred at the top of a monitor, how big it is in logical px, and its
/// corners' radius.
#[derive(Clone, Copy, Debug)]
pub struct Frame {
    /// The monitor; None for the screen's origin.
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

/// Moves and sizes the pill in one request (GTK sends a move and a resize made in one go
/// as one configure request), then lets clicks through everywhere but a rounded rectangle
/// of it, so its transparent corners never take them. On the GTK main thread.
pub fn place(window: &tauri::WebviewWindow, frame: Frame) {
    let target = window.clone();
    let left = (frame.width - frame.shape_width).max(0) / 2;
    let spans: Vec<_> = rounded_spans(frame.shape_width, frame.shape_height, frame.radius)
        .into_iter()
        .map(|(x, y, width, height)| (x + left, y, width, height))
        .collect();
    let _ = window.run_on_main_thread(move || {
        use gtk::prelude::*;
        let Ok(window) = target.gtk_window() else {
            return;
        };
        let (x, y) = top_centre(frame, window.scale_factor());
        // Exactly this size: equal smallest and largest sizes. A window that is not
        // resizable would instead be as big as its webview's natural size, which is the
        // size it last had (200 tall at first), so it could never get smaller.
        let pinned = gtk::gdk::Geometry::new(
            frame.width,
            frame.height,
            frame.width,
            frame.height,
            0,
            0,
            0,
            0,
            0.0,
            0.0,
            gtk::gdk::Gravity::NorthWest,
        );
        window.set_geometry_hints(
            None::<&gtk::Widget>,
            Some(&pinned),
            gtk::gdk::WindowHints::MIN_SIZE | gtk::gdk::WindowHints::MAX_SIZE,
        );
        window.set_size_request(frame.width, frame.height);
        window.move_(x, y);
        window.resize(frame.width, frame.height);
        let region = gtk::cairo::Region::create();
        for (x, y, width, height) in spans {
            let _ = region.union_rectangle(&gtk::cairo::RectangleInt::new(x, y, width, height));
        }
        window.input_shape_combine_region(Some(&region));
    });
}

/// Where a frame's window goes, in the units of a window drawn at `scale` (GTK's, which is
/// fixed when Nest starts, while the monitor's may change later).
fn top_centre(frame: Frame, scale: i32) -> (i32, i32) {
    let Some(area) = frame.monitor else {
        return (0, frame.top);
    };
    let scale = f64::from(scale.max(1));
    let left = f64::from(area.x) / scale;
    let width = f64::from(area.width) / scale;
    (
        (left + (width - f64::from(frame.width)) / 2.0).round() as i32,
        (f64::from(area.y) / scale).round() as i32 + frame.top,
    )
}

/// Sets the scale of every GTK window in Nest (gdk_x11_display_set_window_scale): they
/// redraw at it, keeping their size in their own px. On the GTK main thread.
pub fn set_window_scale(window: &tauri::WebviewWindow, scale: i32) {
    let target = window.clone();
    let _ = window.run_on_main_thread(move || {
        use gtk::prelude::*;
        let display = target
            .gtk_window()
            .ok()
            .map(|window| WidgetExt::display(&window))
            .and_then(|display| display.downcast::<gdkx11::X11Display>().ok());
        if let Some(display) = display {
            display.set_window_scale(scale);
        }
    });
}

/// Calls `changed` on the GTK main thread whenever a monitor changes size, scale or place.
pub fn on_monitors_changed(
    window: &tauri::WebviewWindow,
    changed: impl Fn() + Send + Sync + 'static,
) {
    let changed = std::sync::Arc::new(changed);
    let target = window.clone();
    let on_screen = std::sync::Arc::clone(&changed);
    let _ = window.run_on_main_thread(move || {
        let Some(screen) = target
            .gtk_window()
            .ok()
            .and_then(|window| gtk::prelude::GtkWindowExt::screen(&window))
        else {
            return;
        };
        let on_size = std::sync::Arc::clone(&on_screen);
        screen.connect_monitors_changed(move |_| on_screen());
        screen.connect_size_changed(move |_| on_size());
    });
    // Mutter's new scale in its physical layout leaves the X screen as it was, so GTK hears
    // nothing; Mutter says so on the session bus.
    let target = window.clone();
    let _ = std::thread::Builder::new()
        .name("display-changes".into())
        .spawn(move || {
            let Ok(connection) = zbus::blocking::Connection::session() else {
                return;
            };
            let Some(rule) = zbus::MatchRule::builder()
                .msg_type(zbus::message::Type::Signal)
                .interface("org.gnome.Mutter.DisplayConfig")
                .and_then(|rule| rule.member("MonitorsChanged"))
                .ok()
                .map(|rule| rule.build())
            else {
                return;
            };
            let Ok(signals) =
                zbus::blocking::MessageIterator::for_match_rule(rule, &connection, None)
            else {
                return;
            };
            for _ in signals.flatten() {
                let changed = std::sync::Arc::clone(&changed);
                let _ = target.run_on_main_thread(move || changed());
            }
        });
}

/// A rounded rectangle as rectangles (x, y, width, height): one per row in the corners'
/// rows, one for the straight middle. A row's pixel is in when its centre is.
fn rounded_spans(width: i32, height: i32, radius: f64) -> Vec<(i32, i32, i32, i32)> {
    let radius = radius.clamp(0.0, f64::from(width.min(height)) / 2.0);
    let corner_rows = radius.ceil() as i32;
    let inset = |row: i32| -> i32 {
        let dy = radius - (f64::from(row) + 0.5);
        if dy <= 0.0 {
            return 0;
        }
        (radius - (radius * radius - dy * dy).max(0.0).sqrt()).round() as i32
    };
    let mut spans = Vec::new();
    for row in 0..corner_rows.min(height) {
        let x = inset(row);
        spans.push((x, row, width - 2 * x, 1));
        let mirrored = height - 1 - row;
        if mirrored >= corner_rows {
            spans.push((x, mirrored, width - 2 * x, 1));
        }
    }
    let middle = height - 2 * corner_rows;
    if middle > 0 {
        spans.push((0, corner_rows, width, middle));
    }
    spans
}

/// A server listening on a local TCP port, for the browser's Local servers menu (as the
/// Mac's NestKit LocalServers).
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
pub struct LocalServer {
    pub port: u16,
    pub process: String,
}

/// This user's TCP listeners reachable as localhost, one per port, by port, without the
/// daemon's `skip_port` and Nest's own processes. From lsof when it is installed, else from
/// /proc (Ubuntu does not install lsof by default).
pub fn local_servers(skip_port: u16) -> Vec<LocalServer> {
    let lsof = std::process::Command::new("lsof")
        .args(["-nP", "-iTCP", "-sTCP:LISTEN"])
        .output();
    let mut servers = match lsof {
        Ok(output) if output.status.success() || !output.stdout.is_empty() => {
            parse_lsof(&String::from_utf8_lossy(&output.stdout))
        }
        _ => proc_listeners(),
    };
    servers.retain(|server| {
        server.port != skip_port && !NEST_PROCESSES.contains(&server.process.as_str())
    });
    servers
}

/// Nest's own processes, which are not the user's servers.
const NEST_PROCESSES: &[&str] = &["nest-desktop", "nestd"];

/// Addresses reachable as localhost: any address, or loopback.
fn reachable(host: &str) -> bool {
    matches!(
        host,
        "*" | "127.0.0.1" | "[::1]" | "[::]" | "0.0.0.0" | "localhost"
    )
}

fn one_per_port(found: impl IntoIterator<Item = LocalServer>) -> Vec<LocalServer> {
    let mut by_port = std::collections::BTreeMap::new();
    for server in found {
        by_port.entry(server.port).or_insert(server);
    }
    by_port.into_values().collect()
}

/// `lsof -nP -iTCP -sTCP:LISTEN` lines: COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME,
/// the name `host:port (LISTEN)`.
fn parse_lsof(output: &str) -> Vec<LocalServer> {
    one_per_port(output.lines().filter_map(|line| {
        let fields: Vec<&str> = line.split_whitespace().collect();
        if fields.len() < 3 || fields[fields.len() - 1] != "(LISTEN)" {
            return None;
        }
        let (host, port) = fields[fields.len() - 2].rsplit_once(':')?;
        let port = port.parse().ok()?;
        reachable(host).then(|| LocalServer {
            port,
            process: fields[0].replace("\\x20", " "),
        })
    }))
}

/// The listeners in /proc/net/tcp and tcp6 owned by this user, named after the process
/// holding each socket.
fn proc_listeners() -> Vec<LocalServer> {
    use std::os::unix::fs::MetadataExt;
    let Ok(uid) = std::fs::metadata("/proc/self").map(|meta| meta.uid()) else {
        return Vec::new();
    };
    let mut sockets = Vec::new();
    for table in ["/proc/net/tcp", "/proc/net/tcp6"] {
        if let Ok(text) = std::fs::read_to_string(table) {
            sockets.extend(parse_proc_net(&text, uid));
        }
    }
    let owners = socket_owners();
    one_per_port(sockets.into_iter().filter_map(|(port, inode)| {
        Some(LocalServer {
            port,
            process: owners.get(&inode)?.clone(),
        })
    }))
}

/// /proc/net/tcp(6) rows that listen (state 0A) on a reachable address and belong to `uid`:
/// (port, socket inode).
fn parse_proc_net(text: &str, uid: u32) -> Vec<(u16, u64)> {
    text.lines()
        .skip(1)
        .filter_map(|line| {
            let fields: Vec<&str> = line.split_whitespace().collect();
            let (address, port) = fields.get(1)?.split_once(':')?;
            if *fields.get(3)? != "0A" || fields.get(7)?.parse::<u32>().ok()? != uid {
                return None;
            }
            let local = match address {
                // IPv4, little-endian: 127.0.0.1 and 0.0.0.0.
                "0100007F" | "00000000" => true,
                // IPv6: ::1 and ::.
                "00000000000000000000000001000000" | "00000000000000000000000000000000" => true,
                _ => false,
            };
            let port = u16::from_str_radix(port, 16).ok()?;
            local.then_some((port, fields.get(9)?.parse().ok()?))
        })
        .collect()
}

/// Socket inode to the name of the process holding it, for this user's processes.
fn socket_owners() -> std::collections::HashMap<u64, String> {
    let mut owners = std::collections::HashMap::new();
    let Ok(processes) = std::fs::read_dir("/proc") else {
        return owners;
    };
    for process in processes.flatten() {
        let path = process.path();
        let Ok(fds) = std::fs::read_dir(path.join("fd")) else {
            continue;
        };
        let name = std::fs::read_to_string(path.join("comm")).unwrap_or_default();
        for fd in fds.flatten() {
            let Ok(target) = std::fs::read_link(fd.path()) else {
                continue;
            };
            let target = target.to_string_lossy();
            if let Some(inode) = target
                .strip_prefix("socket:[")
                .and_then(|rest| rest.strip_suffix(']'))
                .and_then(|inode| inode.parse().ok())
            {
                owners.insert(inode, name.trim().to_owned());
            }
        }
    }
    owners
}

/// The daemon's systemd user unit (daemon/src/nestd/service/systemd.py).
const SERVICE_UNIT: &str = "nest.service";

/// How a systemctl call ended: whether it succeeded, and what it said on stderr.
pub struct Ran {
    pub success: bool,
    pub stderr: String,
}

fn systemctl(args: &[&str]) -> Result<Ran, String> {
    let output = std::process::Command::new("systemctl")
        .arg("--user")
        .args(args)
        .output()
        .map_err(|error| format!("Could not run systemctl: {error}"))?;
    Ok(Ran {
        success: output.status.success(),
        stderr: String::from_utf8_lossy(&output.stderr).trim().to_owned(),
    })
}

/// Starts the daemon's user service: "started", or "not_installed" when there is no unit.
pub fn start_service() -> Result<&'static str, String> {
    let found = systemctl(&["cat", SERVICE_UNIT])?;
    let started = if found.success {
        Some(systemctl(&["start", SERVICE_UNIT])?)
    } else {
        None
    };
    service_result(&found, started.as_ref())
}

/// What `systemctl --user cat` (`found`) and then `start` (when it ran) came to.
fn service_result(found: &Ran, started: Option<&Ran>) -> Result<&'static str, String> {
    if !found.success {
        // Without the unit; any other failure (no user bus, say) is an error.
        return if found.stderr.contains("No files found") {
            Ok("not_installed")
        } else {
            Err(failure("look for", found))
        };
    }
    match started {
        Some(started) if started.success => Ok("started"),
        Some(started) => Err(failure("start", started)),
        None => Err(failure("start", found)),
    }
}

fn failure(doing: &str, ran: &Ran) -> String {
    if ran.stderr.is_empty() {
        format!("systemctl could not {doing} {SERVICE_UNIT}")
    } else {
        ran.stderr.clone()
    }
}

/// `file` in the default app for plain text, named by `xdg-mime`, whatever kind of file it
/// is, so nothing runs: false when there is no such app.
pub fn open_in_text_editor(file: &Path) -> Result<bool, String> {
    use gtk::gio::prelude::AppInfoExt;
    let Ok(query) = std::process::Command::new("xdg-mime")
        .args(["query", "default", "text/plain"])
        .output()
    else {
        return Ok(false);
    };
    let app = String::from_utf8_lossy(&query.stdout).trim().to_owned();
    let Some(editor) = gtk::gio::DesktopAppInfo::new(&app) else {
        return Ok(false);
    };
    editor
        .launch(
            &[gtk::gio::File::for_path(file)],
            None::<&gtk::gio::AppLaunchContext>,
        )
        .map(|()| true)
        .map_err(|error| format!("Could not open {}: {error}", file.display()))
}

/// The address of `path` on one of the app's own schemes (Windows serves them as
/// `http://<scheme>.localhost/` instead).
pub fn custom_scheme_url(scheme: &str, path: &str) -> String {
    format!("{scheme}://localhost/{path}")
}

pub fn read_local_token(data_dir: &Path) -> Result<String, String> {
    let path = data_dir.join(TOKEN_SOCKET);
    let mut stream = UnixStream::connect(&path).map_err(|error| match error.kind() {
        ErrorKind::NotFound | ErrorKind::ConnectionRefused => format!(
            "The Nest daemon is not running: nothing answers at {}",
            path.display()
        ),
        _ => format!(
            "Could not reach the Nest daemon at {}: {error}",
            path.display()
        ),
    })?;
    stream
        .set_read_timeout(Some(TOKEN_TIMEOUT))
        .map_err(|error| error.to_string())?;
    let mut answer = String::new();
    stream
        .read_to_string(&mut answer)
        .map_err(|error| format!("Could not read the token from {}: {error}", path.display()))?;
    let token = answer.trim();
    if token.is_empty() {
        // The daemon answers only processes of its own user, and closes on anyone else.
        return Err(format!(
            "The Nest daemon at {} gave no token; it only answers its own user",
            path.display()
        ));
    }
    Ok(token.to_owned())
}

/// The primary monitor's scale, and whether the compositor scales X11 windows itself.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct DisplayScale {
    pub scale: f64,
    pub compositor_scales_x11: bool,
}

/// The variables to set before GTK starts. On Wayland, always-on-top, window placement
/// and global shortcuts only work through XWayland, so Nest asks GTK for X11 while the
/// pill should stay on top, unless the user chose a backend themselves.
///
/// Through XWayland, GTK learns no scale from GNOME on Wayland: in Mutter's default
/// (physical) layout X11 windows are drawn pixel for pixel, so at 200% Nest would be half
/// size. Nest then sets GDK_SCALE to the monitor's scale (`scale` is read only then).
/// Mutter offers fractional scales only in its logical layout, where it scales X11
/// windows itself, so GDK_SCALE stays unset there: it would scale them twice.
pub fn display_env(
    env: Env,
    settings: &Settings,
    scale: impl FnOnce() -> Option<DisplayScale>,
) -> Vec<(&'static str, String)> {
    let mut vars = Vec::new();
    let wayland = var(env, "WAYLAND_DISPLAY").is_some();
    let xwayland = var(env, "DISPLAY").is_some();
    if wayland && xwayland && settings.keep_pill_on_top && var(env, "GDK_BACKEND").is_none() {
        vars.push(("GDK_BACKEND", "x11".to_owned()));
        let chosen = var(env, "GDK_SCALE").is_some() || var(env, "GDK_DPI_SCALE").is_some();
        if !chosen {
            if let Some(gdk_scale) = scale().and_then(gdk_scale) {
                vars.push(("GDK_SCALE", gdk_scale.to_string()));
            }
        }
        // GTK3 draws its own text (dialogs, tooltips) through the X server by default, and
        // some Xwayland setups draw none of it; drawing in the process works everywhere,
        // and the webview measures the same either way.
        if var(env, "GDK_RENDERING").is_none() {
            vars.push(("GDK_RENDERING", "image".to_owned()));
        }
        // GTK draws the title bars of Nest's framed windows (browser windows, dialogs) itself.
        // Under XWayland, Mutter frames other windows from a helper process; once that
        // helper has died (it does, on an X error) a framed window is never shown again
        // until the user logs out, and Nest's browser windows stayed hidden.
        if var(env, "GTK_CSD").is_none() {
            vars.push(("GTK_CSD", "1".to_owned()));
        }
    }
    if settings.disable_dmabuf_renderer && var(env, "WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        vars.push(("WEBKIT_DISABLE_DMABUF_RENDERER", "1".to_owned()));
    }
    vars
}

/// GTK's whole-number scale for X11 windows the compositor leaves unscaled; None at 1x.
fn gdk_scale(display: DisplayScale) -> Option<u32> {
    if display.compositor_scales_x11 || !display.scale.is_finite() {
        return None;
    }
    let scale = display.scale.round().clamp(1.0, 4.0) as u32;
    (scale > 1).then_some(scale)
}

/// Mutter's scale for the primary monitor (org.gnome.Mutter.DisplayConfig), else GNOME's
/// interface scaling factor, which only X11-era settings set; None without either.
/// `log` hears what each source answered (NEST_DEBUG_DISPLAY).
pub fn read_display_scale(log: &dyn Fn(String)) -> Option<DisplayScale> {
    match mutter_scale() {
        Ok(scale) => {
            log(format!("mutter: {scale:?}"));
            return Some(scale);
        }
        Err(error) => log(format!("mutter: {error}")),
    }
    let scale = gsettings_scale();
    log(format!("gsettings scaling-factor: {scale:?}"));
    scale
}

type MutterMode = (
    String,
    i32,
    i32,
    f64,
    f64,
    Vec<f64>,
    std::collections::HashMap<String, zbus::zvariant::OwnedValue>,
);
type MutterMonitor = (
    (String, String, String, String),
    Vec<MutterMode>,
    std::collections::HashMap<String, zbus::zvariant::OwnedValue>,
);
type MutterLogicalMonitor = (
    i32,
    i32,
    f64,
    u32,
    bool,
    Vec<(String, String, String, String)>,
    std::collections::HashMap<String, zbus::zvariant::OwnedValue>,
);
/// Mutter's `layout-mode` property: 1 is logical (it scales X11 windows), 2 physical.
const LOGICAL_LAYOUT: u32 = 1;

fn mutter_scale() -> Result<DisplayScale, String> {
    let connection =
        zbus::blocking::Connection::session().map_err(|e| format!("no session bus: {e}"))?;
    let reply = connection
        .call_method(
            Some("org.gnome.Mutter.DisplayConfig"),
            "/org/gnome/Mutter/DisplayConfig",
            Some("org.gnome.Mutter.DisplayConfig"),
            "GetCurrentState",
            &(),
        )
        .map_err(|e| format!("GetCurrentState failed: {e}"))?;
    let (_serial, _monitors, logical, properties): (
        u32,
        Vec<MutterMonitor>,
        Vec<MutterLogicalMonitor>,
        std::collections::HashMap<String, zbus::zvariant::OwnedValue>,
    ) = reply
        .body()
        .deserialize()
        .map_err(|e| format!("unexpected GetCurrentState reply: {e}"))?;
    let primary = logical
        .iter()
        .find(|monitor| monitor.4)
        .or(logical.first())
        .ok_or("no logical monitor")?;
    let layout = properties
        .get("layout-mode")
        .and_then(|mode| u32::try_from(mode).ok());
    Ok(DisplayScale {
        scale: primary.2,
        // Without the property (an older Mutter) Nest does not know, so it leaves GTK be.
        compositor_scales_x11: layout.is_none_or(|layout| layout == LOGICAL_LAYOUT),
    })
}

fn gsettings_scale() -> Option<DisplayScale> {
    let output = std::process::Command::new("gsettings")
        .args(["get", "org.gnome.desktop.interface", "scaling-factor"])
        .output()
        .ok()?;
    let text = String::from_utf8(output.stdout).ok()?;
    let factor: u32 = text
        .trim()
        .trim_start_matches("uint32")
        .trim()
        .parse()
        .ok()?;
    Some(DisplayScale {
        scale: f64::from(factor.max(1)),
        compositor_scales_x11: false,
    })
}

#[cfg(test)]
mod tests {
    use std::io::Write;
    use std::os::unix::net::UnixListener;
    use std::thread;

    use super::*;
    use crate::env::fake;
    use crate::testing::TempDir;

    /// Answers one connection like the daemon: the reply, then end of stream.
    fn serve_once(dir: &Path, reply: &'static str) -> thread::JoinHandle<()> {
        let listener = UnixListener::bind(dir.join(TOKEN_SOCKET)).unwrap();
        thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream.write_all(reply.as_bytes()).unwrap();
            stream.shutdown(std::net::Shutdown::Write).unwrap();
            let _ = stream.read_to_end(&mut Vec::new());
        })
    }

    #[test]
    fn reads_the_token_from_the_daemon_socket() {
        let dir = TempDir::new("token");
        let server = serve_once(dir.path(), "secret-token\n");

        assert_eq!(read_local_token(dir.path()).unwrap(), "secret-token");
        server.join().unwrap();
    }

    #[test]
    fn a_missing_socket_says_the_daemon_is_not_running() {
        let dir = TempDir::new("token");

        let error = read_local_token(dir.path()).unwrap_err();

        assert!(error.contains("not running"), "{error}");
        assert!(error.contains("token.sock"), "{error}");
    }

    #[test]
    fn a_refused_request_is_an_error_not_an_empty_token() {
        let dir = TempDir::new("token");
        let server = serve_once(dir.path(), "");

        let error = read_local_token(dir.path()).unwrap_err();

        assert!(error.contains("gave no token"), "{error}");
        server.join().unwrap();
    }

    fn display_vars(vars: &[(&str, &str)], settings: &Settings) -> Vec<&'static str> {
        let env = fake(vars);
        display_env(&env, settings, || None)
            .into_iter()
            .map(|(name, _)| name)
            .collect()
    }

    const SESSION: [(&str, &str); 2] = [("WAYLAND_DISPLAY", "wayland-0"), ("DISPLAY", ":0")];

    fn scaled(
        vars: &[(&str, &str)],
        scale: f64,
        compositor_scales_x11: bool,
    ) -> Vec<(&'static str, String)> {
        let env = fake(vars);
        let display = DisplayScale {
            scale,
            compositor_scales_x11,
        };
        display_env(&env, &Settings::default(), || Some(display))
    }

    /// What Nest sets when it chose XWayland, with `scale` as GDK_SCALE if given.
    fn xwayland(scale: Option<&str>) -> Vec<(&'static str, String)> {
        let mut vars = vec![("GDK_BACKEND", "x11".to_owned())];
        if let Some(scale) = scale {
            vars.push(("GDK_SCALE", scale.to_owned()));
        }
        vars.push(("GDK_RENDERING", "image".to_owned()));
        vars.push(("GTK_CSD", "1".to_owned()));
        vars
    }

    #[test]
    fn xwayland_at_200_percent_draws_at_2x() {
        assert_eq!(scaled(&SESSION, 2.0, false), xwayland(Some("2")));
        // 100%, and Mutter's logical layout, which scales X11 windows itself.
        assert_eq!(scaled(&SESSION, 1.0, false), xwayland(None));
        assert_eq!(scaled(&SESSION, 1.5, true), xwayland(None));
        assert_eq!(scaled(&SESSION, 2.0, true), xwayland(None));
    }

    #[test]
    fn the_scale_is_left_to_the_user_and_to_native_wayland() {
        let mut chosen = SESSION.to_vec();
        chosen.push(("GDK_SCALE", "1"));
        assert_eq!(scaled(&chosen, 2.0, false), xwayland(None));
        let mut dpi = SESSION.to_vec();
        dpi.push(("GDK_DPI_SCALE", "1.5"));
        assert_eq!(scaled(&dpi, 2.0, false), xwayland(None));
        // Without XWayland GTK takes the scale from Wayland itself, and nobody asks Mutter.
        let not_on_top = Settings {
            keep_pill_on_top: false,
            ..Settings::default()
        };
        let env = fake(&SESSION);
        let vars = display_env(&env, &not_on_top, || panic!("no need to read the scale"));
        assert!(vars.is_empty());
    }

    #[test]
    fn gtk_draws_itself_through_xwayland_unless_the_user_chose() {
        assert_eq!(scaled(&SESSION, 1.0, false), xwayland(None));
        let mut chosen = SESSION.to_vec();
        chosen.push(("GDK_RENDERING", "similar"));
        chosen.push(("GTK_CSD", "0"));
        assert_eq!(
            scaled(&chosen, 1.0, false),
            vec![("GDK_BACKEND", "x11".to_owned())]
        );
    }

    #[test]
    fn wayland_uses_xwayland_while_the_pill_stays_on_top() {
        let on_top = Settings::default();
        let session = SESSION;
        let env = fake(&session);
        assert_eq!(display_env(&env, &on_top, || None), xwayland(None));

        let not_on_top = Settings {
            keep_pill_on_top: false,
            ..Settings::default()
        };
        assert!(display_vars(&session, &not_on_top).is_empty());
    }

    #[test]
    fn xwayland_is_left_alone_when_it_cannot_help_or_was_chosen() {
        let settings = Settings::default();
        // An X11 session already has what the pill needs.
        assert!(display_vars(&[("DISPLAY", ":0")], &settings).is_empty());
        // Wayland without Xwayland: GTK could not open an X11 display.
        assert!(display_vars(&[("WAYLAND_DISPLAY", "wayland-0")], &settings).is_empty());
        // The user picked a backend.
        let chosen = [
            ("WAYLAND_DISPLAY", "wayland-0"),
            ("DISPLAY", ":0"),
            ("GDK_BACKEND", "wayland"),
        ];
        assert!(display_vars(&chosen, &settings).is_empty());
    }

    #[test]
    fn local_servers_from_lsof_are_the_localhost_listeners_one_per_port() {
        let output = "\
COMMAND     PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
node       4242 me     23u  IPv4  91233      0t0  TCP 127.0.0.1:5173 (LISTEN)
node       4242 me     24u  IPv6  91234      0t0  TCP [::1]:5173 (LISTEN)
python3    4300 me      5u  IPv4  91300      0t0  TCP *:8000 (LISTEN)
Web\\x20Con 4400 me      7u  IPv6  91400      0t0  TCP [::]:3000 (LISTEN)
postgres   4500 me      6u  IPv4  91500      0t0  TCP 192.168.1.5:5432 (LISTEN)
node       4242 me     25u  IPv4  91235      0t0  TCP 127.0.0.1:5173->127.0.0.1:50000 (ESTABLISHED)
";
        let server = |port: u16, process: &str| LocalServer {
            port,
            process: process.to_owned(),
        };
        assert_eq!(
            parse_lsof(output),
            vec![
                server(3000, "Web Con"),
                server(5173, "node"),
                server(8000, "python3")
            ]
        );
    }

    #[test]
    fn local_servers_from_proc_are_this_users_localhost_listeners() {
        let table = "\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:1435 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 91233 1
   1: 00000000:1F40 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 91300 1
   2: 0501A8C0:1538 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 91500 1
   3: 0100007F:2E8C 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1001        0 91600 1
   4: 0100007F:1435 0100007F:C350 01 00000000:00000000 00:00000000 00000000  1000        0 91235 1
";
        assert_eq!(
            parse_proc_net(table, 1000),
            vec![(5173, 91233), (8000, 91300)]
        );
        let tcp6 = "\
  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000000000000000000001000000:1435 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 91234 1
";
        assert_eq!(parse_proc_net(tcp6, 1000), vec![(5173, 91234)]);
    }

    #[test]
    fn starting_the_service_says_started_not_installed_or_why_not() {
        let ran = |success: bool, stderr: &str| Ran {
            success,
            stderr: stderr.to_owned(),
        };
        let found = ran(true, "");
        assert_eq!(service_result(&found, Some(&ran(true, ""))), Ok("started"));
        assert_eq!(
            service_result(&ran(false, "No files found for nest.service."), None),
            Ok("not_installed")
        );
        // Not "not installed": systemd itself could not be asked.
        let no_bus = ran(false, "Failed to connect to bus: No medium found");
        assert_eq!(
            service_result(&no_bus, None),
            Err("Failed to connect to bus: No medium found".to_owned())
        );
        let refused = ran(false, "Job for nest.service failed.");
        assert_eq!(
            service_result(&found, Some(&refused)),
            Err("Job for nest.service failed.".to_owned())
        );
        assert_eq!(
            service_result(&found, Some(&ran(false, ""))),
            Err("systemctl could not start nest.service".to_owned())
        );
    }

    #[test]
    fn a_notification_click_runs_its_action_once_and_only_until_it_closes() {
        use std::sync::atomic::{AtomicU32, Ordering};
        use std::sync::Arc;

        let runs = Arc::new(AtomicU32::new(0));
        let counting = || {
            let runs = Arc::clone(&runs);
            Box::new(move || {
                runs.fetch_add(1, Ordering::SeqCst);
            }) as OnClick
        };
        let clicks = Clicks::default();
        clicks.pending.lock().unwrap().insert(1, counting());
        clicks.pending.lock().unwrap().insert(2, counting());

        clicks.invoked(1, "other-button");
        assert_eq!(runs.load(Ordering::SeqCst), 0);
        clicks.invoked(1, "default");
        clicks.invoked(1, "default");
        assert_eq!(runs.load(Ordering::SeqCst), 1);

        clicks.closed(2);
        clicks.invoked(2, "default");
        assert_eq!(runs.load(Ordering::SeqCst), 1);
    }

    fn takes_click(spans: &[(i32, i32, i32, i32)], x: i32, y: i32) -> bool {
        spans
            .iter()
            .any(|&(sx, sy, w, h)| x >= sx && x < sx + w && y >= sy && y < sy + h)
    }

    // Regression (B117 VM check): after the display went from 100% to 200% while Nest ran,
    // the pill sat left of the centre, placed in the monitor's new units while GTK still
    // drew at its starting scale.
    #[test]
    fn the_pill_is_centred_in_the_units_gtk_draws_in() {
        let frame = |monitor| Frame {
            monitor,
            top: 8,
            width: 420,
            height: 34,
            shape_width: 176,
            shape_height: 34,
            radius: 17.0,
        };
        let uhd = Area {
            x: 0,
            y: 0,
            width: 3840,
            height: 2160,
        };
        // Started at 2x: logical px, half the physical.
        assert_eq!(top_centre(frame(Some(uhd)), 2), (750, 8));
        // Started at 1x: GTK's px are physical px.
        assert_eq!(top_centre(frame(Some(uhd)), 1), (1710, 8));
        let second = Area {
            x: 3840,
            y: 200,
            width: 1920,
            height: 1080,
        };
        assert_eq!(top_centre(frame(Some(second)), 1), (3840 + 750, 208));
        assert_eq!(top_centre(frame(None), 2), (0, 8));
    }

    #[test]
    fn the_pill_takes_clicks_only_inside_its_rounded_shape() {
        for (height, radius) in [(38, 19.0), (180, 22.0)] {
            let spans = rounded_spans(400, height, radius);
            let bottom = height - 1;
            for (x, y) in [(0, 0), (399, 0), (0, bottom), (399, bottom), (2, 2)] {
                assert!(!takes_click(&spans, x, y), "corner {x},{y} of 400x{height}");
            }
            for (x, y) in [
                (200, 0),
                (200, bottom),
                (0, height / 2),
                (399, height / 2),
                (200, 19),
            ] {
                assert!(takes_click(&spans, x, y), "inside {x},{y} of 400x{height}");
            }
            let rows: std::collections::BTreeSet<i32> =
                spans.iter().flat_map(|&(_, y, _, h)| y..y + h).collect();
            assert_eq!(
                rows.len() as i32,
                height,
                "every row of 400x{height} is covered"
            );
        }
    }

    #[test]
    fn the_dmabuf_renderer_is_turned_off_only_by_the_setting() {
        assert!(display_vars(&[], &Settings::default()).is_empty());
        let off = Settings {
            disable_dmabuf_renderer: true,
            ..Settings::default()
        };
        assert_eq!(
            display_vars(&[], &off),
            vec!["WEBKIT_DISABLE_DMABUF_RENDERER"]
        );
    }
}
