//! Nest's windows: the main window, the pixie pill and browser windows.

use std::sync::atomic::{AtomicU32, Ordering};

use tauri::{
    AppHandle, Emitter, Manager, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder, Window,
};
use tauri_plugin_opener::OpenerExt;

use crate::commands::AppState;
use crate::{artifact, external};

pub const MAIN: &str = "main";
/// The main window's smallest inside, in the page's px.
const MAIN_MIN: (f64, f64) = (1000.0, 640.0);
/// Sent to a window when it is maximized or restored; payload: the new state (bool).
pub const MAXIMIZED_EVENT: &str = "nest://maximized";
pub const PILL: &str = "pill";
/// Browser windows are labelled `browser-<n>`; no capability names them, so pages there
/// cannot call any command.
pub const BROWSER_PREFIX: &str = "browser-";
const MAIN_PAGE: &str = "desktop.html";
const PILL_PAGE: &str = "desktop.html?view=pill";
/// What the pill page asked for (web/src/desktop/pillSize.ts), in logical px: its shape,
/// which takes clicks, centred at the top of the window, and the window's height, never
/// less than the shape's. The window keeps its height while the pill eases closed, and the
/// shape lets clicks through there at once.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PillSize {
    pub width: f64,
    pub height: f64,
    pub room: f64,
}

impl PillSize {
    /// This size with the page's change; a new height without a room makes the window as
    /// tall as the shape.
    pub fn with(self, width: Option<f64>, height: Option<f64>, room: Option<f64>) -> Self {
        let width = width.unwrap_or(self.width).max(1.0);
        let height = height.unwrap_or(self.height).max(1.0);
        let room = match room {
            Some(room) => room,
            None if height == self.height => self.room,
            None => height,
        };
        Self {
            width,
            height,
            room: room.max(height),
        }
    }
}

// The idle pill until its page asks for its size.
pub const PILL_SIZE: PillSize = PillSize {
    width: 176.0,
    height: 34.0,
    room: 34.0,
};
const PILL_TOP_MARGIN: i32 = 8;

/// Pages of the bundled UI (tauri://localhost, or the dev server while developing).
fn is_app_url(url: &Url, dev_url: Option<&Url>) -> bool {
    let local = match url.scheme() {
        "tauri" => url.host_str() == Some("localhost"),
        "http" | "https" => url.host_str() == Some("tauri.localhost"),
        _ => false,
    };
    local || dev_url.is_some_and(|dev| dev.origin() == url.origin())
}

/// Keeps an app window on the bundled UI; links open elsewhere (see below).
fn app_navigation(app: &AppHandle) -> impl Fn(&Url) -> bool + Send + 'static {
    let app = app.clone();
    let dev_url = if tauri::is_dev() {
        app.config().build.dev_url.clone()
    } else {
        None
    };
    move |url| {
        // Frames pass this check too: artifact frames load from their own scheme.
        let artifact_frame = url.scheme() == artifact::SCHEME;
        if is_app_url(url, dev_url.as_ref()) || url.scheme() == "about" || artifact_frame {
            return true;
        }
        // Links leave for the system browser or mail app, as on the Mac; pages on this
        // machine (dev servers) open in a Nest browser window, next to the work.
        let app = app.clone();
        let url = url.clone();
        if external::is_local_page(&url) {
            tauri::async_runtime::spawn(async move {
                if let Err(error) = open_browser(&app, url.as_str(), "") {
                    eprintln!("nest: could not open {url}: {error}");
                }
            });
        } else if external::external_url(url.as_str()).is_ok() {
            if let Err(error) = app.opener().open_url(url.as_str(), None::<&str>) {
                eprintln!("nest: could not open {url}: {error}");
            }
        }
        false
    }
}

pub fn create_main(app: &AppHandle) -> tauri::Result<WebviewWindow> {
    WebviewWindowBuilder::new(app, MAIN, WebviewUrl::App(MAIN_PAGE.into()))
        .title("Nest")
        .inner_size(1280.0, 820.0)
        // The Mac's smallest window (RootView.swift).
        .min_inner_size(MAIN_MIN.0, MAIN_MIN.1)
        .decorations(false)
        .visible(false)
        .on_navigation(app_navigation(app))
        .build()
}

/// Brings the main window back, hidden or minimised, focused (platform::activate says how).
pub fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(MAIN) {
        crate::platform::activate(&window);
    }
}

/// Tells the window when its maximized state changed, so its title bar can switch
/// between the maximize and restore buttons. Resizes come often; only changes are sent.
pub fn report_maximized(window: &Window) {
    let Ok(maximized) = window.is_maximized() else {
        return;
    };
    let state = window.state::<AppState>();
    let previous = state
        .maximized
        .lock()
        .unwrap()
        .insert(window.label().to_owned(), maximized);
    if previous != Some(maximized) {
        let _ = window
            .app_handle()
            .emit_to(window.label(), MAXIMIZED_EVENT, maximized);
    }
}

pub fn create_pill(app: &AppHandle, on_top: bool) -> tauri::Result<WebviewWindow> {
    let pill = WebviewWindowBuilder::new(app, PILL, WebviewUrl::App(PILL_PAGE.into()))
        .title("Nest pixies")
        .inner_size(PILL_SIZE.width, PILL_SIZE.room)
        .decorations(false)
        .transparent(true)
        .shadow(false)
        // Resizable, so it can get smaller; its size is pinned by place_pill and its presses
        // kept from tao (platform::never_focus).
        .resizable(true)
        .always_on_top(on_top)
        .skip_taskbar(true)
        // Like the Mac's island it never takes the keyboard, so a click on it leaves typing
        // where it was.
        .focused(false)
        .focusable(false)
        .visible(false)
        .on_navigation(app_navigation(app))
        .build()?;
    crate::platform::never_focus(&pill);
    place_pill(&pill, PILL_SIZE)?;
    keep_pill_placed(&pill);
    Ok(pill)
}

/// The pill window's width: the open pill's (LIST_WIDTH in web/src/desktop/Pill.tsx).
const PILL_WINDOW_WIDTH: f64 = 420.0;

/// Centres the pill window at the top of the primary monitor, `size.room` tall, taking
/// clicks only on the pill's shape centred at its top.
///
/// The window keeps one width and grows only downwards: when it grew sideways on hover, a
/// click already on its way was handled against the moved page and missed the strip. The
/// input shape follows the pill, so the window's empty sides let clicks through.
pub fn place_pill(pill: &WebviewWindow, size: PillSize) -> tauri::Result<()> {
    let PillSize {
        width,
        height,
        room,
    } = size;
    let window_width = width.max(PILL_WINDOW_WIDTH);
    let monitor = match pill.primary_monitor()? {
        Some(monitor) => Some(monitor),
        None => pill.current_monitor()?,
    };
    // In physical px: the platform turns it into the window's own units, whose scale can
    // differ from the monitor's after the display's scale changed while Nest ran.
    let monitor = monitor.map(|monitor| {
        let (origin, area) = (monitor.position(), monitor.size());
        crate::platform::Area {
            x: origin.x,
            y: origin.y,
            width: area.width as i32,
            height: area.height as i32,
        }
    });
    let frame = crate::platform::Frame {
        monitor,
        top: PILL_TOP_MARGIN,
        width: window_width.round() as i32,
        height: room.round() as i32,
        shape_width: width.round() as i32,
        shape_height: height.round() as i32,
        // The page's corners: 17 collapsed (half the 34 strip), 20 open (desktop.css).
        radius: (height / 2.0).min(20.0),
    };
    crate::diagnostics::display(&format!("pill placed: {frame:?}"));
    crate::platform::place(pill, frame);
    Ok(())
}

/// The pointer at `cursor` on the desktop in a window whose inside starts at `origin` and
/// is `size` big (all physical px), in the window's logical px; None outside the window.
pub fn pointer_in(
    cursor: (f64, f64),
    origin: (i32, i32),
    size: (u32, u32),
    scale: f64,
) -> Option<(f64, f64)> {
    let x = cursor.0 - f64::from(origin.0);
    let y = cursor.1 - f64::from(origin.1);
    let inside = x >= 0.0 && y >= 0.0 && x < f64::from(size.0) && y < f64::from(size.1);
    let scale = if scale > 0.0 { scale } else { 1.0 };
    inside.then_some((x / scale, y / scale))
}

/// Places the pill again whenever the monitors change (a new scale or resolution).
pub fn keep_pill_placed(pill: &WebviewWindow) {
    let target = pill.clone();
    crate::platform::on_monitors_changed(pill, move || {
        let size = *target.state::<AppState>().pill_size.lock().unwrap();
        let _ = place_pill(&target, size);
    });
}

/// Where a window `size` big at `position` goes to be wholly on `area` (all physical px):
/// as near as it can be, or at the area's top left when it is bigger.
pub fn clamp_into(
    position: (i32, i32),
    size: (u32, u32),
    area: (i32, i32, u32, u32),
) -> (i32, i32) {
    let axis = |at: i32, length: u32, start: i32, room: u32| {
        let end = start + room as i32 - length as i32;
        if end < start {
            start
        } else {
            at.clamp(start, end)
        }
    };
    (
        axis(position.0, size.0, area.0, area.2),
        axis(position.1, size.1, area.1, area.3),
    )
}

/// Moves the main window wholly onto the work area of the monitor under its middle (else
/// the primary one), from `position` if given, else from where it is.
pub fn keep_main_on_screen(
    main: &WebviewWindow,
    position: Option<(i32, i32)>,
    size: Option<tauri::PhysicalSize<u32>>,
) -> tauri::Result<()> {
    if main.is_maximized()? || main.is_fullscreen()? {
        return Ok(());
    }
    let size = match size {
        Some(size) => size,
        None => main.outer_size()?,
    };
    let (x, y) = match position {
        Some(position) => position,
        None => {
            let at = main.outer_position()?;
            (at.x, at.y)
        }
    };
    let middle = (
        f64::from(x) + f64::from(size.width) / 2.0,
        f64::from(y) + f64::from(size.height) / 2.0,
    );
    let monitor = match main.monitor_from_point(middle.0, middle.1)? {
        Some(monitor) => Some(monitor),
        None => main.primary_monitor()?,
    };
    let Some(monitor) = monitor else {
        return Ok(());
    };
    let area = monitor.work_area();
    let fitted = tauri::PhysicalSize::new(
        size.width.min(area.size.width),
        size.height.min(area.size.height),
    );
    if fitted != size {
        main.set_size(fitted)?;
    }
    let size = fitted;
    let target = clamp_into(
        (x, y),
        (size.width, size.height),
        (
            area.position.x,
            area.position.y,
            area.size.width,
            area.size.height,
        ),
    );
    if position.is_some() || target != (x, y) {
        main.set_position(tauri::PhysicalPosition::new(target.0, target.1))?;
    }
    Ok(())
}

/// Follows the display: on a new scale, the pages' zoom and the windows' sizes change so
/// Nest keeps its size on screen, then the main window is fitted onto the work area.
pub fn keep_main_placed(main: &WebviewWindow) {
    let target = main.clone();
    crate::platform::on_monitors_changed(main, move || {
        let _ = follow_display_scale(&target);
        // Fitted once the change has settled: right after it, the screen and the monitor's
        // work area can still be the old ones.
        let later = target.clone();
        std::thread::spawn(move || {
            std::thread::sleep(SETTLE_AFTER_DISPLAY_CHANGE);
            let main = later.clone();
            let _ = later.run_on_main_thread(move || {
                let _ = keep_main_on_screen(&main, None, None);
                if let Some(pill) = main.app_handle().get_webview_window(PILL) {
                    let size = *main.state::<AppState>().pill_size.lock().unwrap();
                    let _ = place_pill(&pill, size);
                }
            });
        });
    });
}

const SETTLE_AFTER_DISPLAY_CHANGE: std::time::Duration = std::time::Duration::from_millis(1500);

/// GTK's scale is set when Nest starts (GDK_SCALE); when the display's scale changes later,
/// GTK's follows, so every window looks as it would after a fresh start at the new scale,
/// at the same size in its own px.
pub fn follow_display_scale(main: &WebviewWindow) -> tauri::Result<()> {
    if !main.state::<AppState>().follow_display {
        return Ok(());
    }
    let gtk_scale = main.scale_factor()?;
    let display = crate::platform::read_display_scale(&|_| {});
    let scale = new_gtk_scale(
        gtk_scale,
        display.map(|display| (display.scale, display.compositor_scales_x11)),
    );
    crate::diagnostics::display(&format!(
        "display changed: GTK scale {gtk_scale}, display {display:?}, new GTK scale {scale:?}"
    ));
    if let Some(scale) = scale {
        crate::platform::set_window_scale(main, scale);
    }
    Ok(())
}

/// GTK's new scale for a display at `display` (its scale, and whether the compositor scales
/// X11 windows itself) when GTK draws at `gtk_scale`; None to leave it.
pub fn new_gtk_scale(gtk_scale: f64, display: Option<(f64, bool)>) -> Option<i32> {
    let (scale, compositor_scales) = display?;
    if compositor_scales || !scale.is_finite() {
        return None;
    }
    let wanted = scale.round().clamp(1.0, 4.0);
    ((wanted - gtk_scale).abs() > 0.01).then_some(wanted as i32)
}

/// The browser window `label`; never one of Nest's own windows.
pub fn browser_window(app: &AppHandle, label: &str) -> Result<WebviewWindow, String> {
    if !label.starts_with(BROWSER_PREFIX) {
        return Err(format!("Not a browser window: {label}"));
    }
    app.get_webview_window(label)
        .ok_or_else(|| format!("No browser window {label}"))
}

/// Sent to the main window when a browser window closes; payload: its label.
pub const BROWSER_CLOSED_EVENT: &str = "nest://browser-closed";

/// Shows `url` in the browser window `browser` and brings it forward.
pub fn navigate_browser(browser: &WebviewWindow, url: &str) -> Result<(), String> {
    let url = web_url(url)?;
    browser
        .navigate(url)
        .map_err(|error| format!("Could not open the page: {error}"))?;
    crate::platform::activate(browser);
    Ok(())
}

fn web_url(url: &str) -> Result<Url, String> {
    let parsed: Url = url
        .parse()
        .map_err(|_| format!("Not a web address: {url}"))?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return Err(format!(
            "Only http and https pages open in a browser window: {url}"
        ));
    }
    Ok(parsed)
}

pub fn open_browser(app: &AppHandle, url: &str, title: &str) -> Result<String, String> {
    static NEXT: AtomicU32 = AtomicU32::new(1);
    let url = web_url(url)?;
    let label = format!("{BROWSER_PREFIX}{}", NEXT.fetch_add(1, Ordering::Relaxed));
    let title = if title.trim().is_empty() {
        url.host_str().unwrap_or("Nest").to_owned()
    } else {
        title.to_owned()
    };
    let browser = WebviewWindowBuilder::new(app, &label, WebviewUrl::External(url))
        .title(title)
        .inner_size(1100.0, 780.0)
        // Shown by activate below, with a user time GNOME accepts.
        .visible(false)
        // A page there may go anywhere on the web, but never to the app's own pages.
        .on_navigation(|url| matches!(url.scheme(), "http" | "https" | "about" | "blob" | "data"))
        .build()
        .map_err(|error| format!("Could not open a browser window: {error}"))?;
    crate::platform::close_on_ctrl_w(&browser);
    // In front and focused: asked for without a user time, GNOME stacks a new window under
    // the focused one, here behind Nest's own window, where it seems never to open.
    crate::platform::activate(&browser);
    Ok(label)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gtk_follows_the_display_scale_changed_while_nest_runs() {
        // Started at 2x, the display now at 1x, and the other way.
        assert_eq!(new_gtk_scale(2.0, Some((1.0, false))), Some(1));
        assert_eq!(new_gtk_scale(1.0, Some((2.0, false))), Some(2));
        // Unchanged, unknown, or the compositor scales X11 windows itself.
        assert_eq!(new_gtk_scale(2.0, Some((2.0, false))), None);
        assert_eq!(new_gtk_scale(2.0, None), None);
        assert_eq!(new_gtk_scale(1.0, Some((1.5, true))), None);
    }

    #[test]
    fn a_window_off_screen_comes_back_onto_the_work_area() {
        // A 1920x1080 monitor whose top bar takes 32 px.
        let area = (0, 32, 1920, 1048);
        // After a 2x to 1x change it sat at x = -506.
        assert_eq!(clamp_into((-506, 100), (1280, 820), area), (0, 100));
        assert_eq!(clamp_into((1500, 900), (1280, 820), area), (640, 260));
        assert_eq!(clamp_into((300, 0), (1280, 820), area), (300, 32));
        // Already on screen: left where it is.
        assert_eq!(clamp_into((100, 200), (1280, 820), area), (100, 200));
        // Bigger than the area: its top left.
        assert_eq!(clamp_into((-50, -50), (2560, 1640), area), (0, 32));
        // A second monitor to the right.
        assert_eq!(
            clamp_into((5000, 40), (1280, 820), (1920, 0, 2560, 1440)),
            (3200, 40)
        );
    }

    #[test]
    fn the_pill_window_is_never_shorter_than_what_takes_clicks() {
        let open = PILL_SIZE.with(Some(420.0), Some(150.0), Some(150.0));
        assert_eq!(open.room, 150.0);
        // Easing closed: the shape is the strip at once, the window keeps its height.
        let closing = open.with(Some(176.0), Some(34.0), Some(150.0));
        assert_eq!((closing.height, closing.room), (34.0, 150.0));
        // A room below the shape is raised to it.
        assert_eq!(closing.with(None, Some(90.0), Some(40.0)).room, 90.0);
        // A new height without a room makes the window as tall as the shape.
        assert_eq!(closing.with(None, Some(60.0), None).room, 60.0);
        // Only showing it keeps what it had.
        assert_eq!(closing.with(None, None, None), closing);
    }

    #[test]
    fn the_pointer_is_found_in_the_pill_window_in_its_own_px() {
        // A 420 by 34 window at (750, 32) at 1x, and 840 by 68 at (1500, 64) at 2x.
        assert_eq!(
            pointer_in((960.0, 49.0), (750, 32), (420, 34), 1.0),
            Some((210.0, 17.0))
        );
        assert_eq!(
            pointer_in((1920.0, 98.0), (1500, 64), (840, 68), 2.0),
            Some((210.0, 17.0))
        );
        // Beside it and below it.
        assert_eq!(pointer_in((749.0, 49.0), (750, 32), (420, 34), 1.0), None);
        assert_eq!(pointer_in((960.0, 66.0), (750, 32), (420, 34), 1.0), None);
    }

    #[test]
    fn only_the_bundled_ui_counts_as_the_app() {
        let url = |text: &str| text.parse::<Url>().unwrap();
        assert!(is_app_url(
            &url("tauri://localhost/desktop.html?view=pill"),
            None
        ));
        assert!(is_app_url(
            &url("http://tauri.localhost/desktop.html"),
            None
        ));
        assert!(!is_app_url(&url("https://example.com/"), None));
        assert!(!is_app_url(&url("http://127.0.0.1:8765/"), None));
        assert!(!is_app_url(
            &url("http://localhost:5173/desktop.html"),
            None
        ));

        let dev = url("http://localhost:5173");
        assert!(is_app_url(
            &url("http://localhost:5173/desktop.html"),
            Some(&dev)
        ));
        assert!(!is_app_url(&url("http://localhost:5174/"), Some(&dev)));
    }
}
