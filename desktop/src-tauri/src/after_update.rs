//! Relaunch to update with a new app opens it once (B130): the app starts this helper and
//! quits. The helper waits a moment for the daemon to come back, then swaps to the new app
//! and opens it, or opens the old one as it is when the update went back. A daemon slower
//! than that gets the old app back at once, which shows the update's progress and swaps
//! itself once the new version answers, so Nest is never gone for long. Without the helper
//! the old app would load again after the daemon's restart, only to quit for the swap. It
//! starts detached, so what it does goes to `<data>/logs/app-update.log`. As the Mac's
//! AppRestarter.swift.

use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::app_swap::{self, Install};
use crate::{daemon, env, install};

/// The first argument that makes a Nest process this helper, with no window.
pub const HELPER_ARG: &str = "--nest-after-update";
/// How long the new daemon gets before the old app opens; most updates answer in a few
/// seconds.
const NEW_APP_WAIT: Duration = Duration::from_secs(10);
const APP_WAIT: Duration = Duration::from_secs(10);
const POLL: Duration = Duration::from_millis(500);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(2);
const LOG_FILE: &str = "app-update.log";

/// Starts the helper from the install, in a session of its own, for the app to quit next.
pub fn start(install: &Install, version: &str, scrub: &[String]) -> Result<(), String> {
    let mut command = Command::new(install.program());
    command
        .arg(HELPER_ARG)
        .arg(std::process::id().to_string())
        .arg(version)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    app_swap::scrub(&mut command, scrub);
    install::detach(&mut command);
    command
        .spawn()
        .map(drop)
        .map_err(|error| format!("Could not start the update: {error}"))
}

#[derive(Debug, PartialEq, Eq)]
enum Next {
    Wait,
    OpenNew,
    OpenOld,
}

/// What the daemon's answer means. The old daemon can still answer for a moment after the
/// relaunch, so another version counts as the update going back only once the watcher has
/// cleared `updating`.
fn next(new: &str, answered: Option<&str>, updating: bool) -> Next {
    match answered {
        Some(version) if version == new => Next::OpenNew,
        Some(_) if !updating => Next::OpenOld,
        _ => Next::Wait,
    }
}

/// What the wait for the new daemon ended with.
#[derive(Debug, PartialEq, Eq)]
enum Outcome {
    New,
    // The update went back: the version that answers.
    Old(String),
    NotBack,
}

/// Asks the daemon at `base` until it answers on `version`, the update goes back, or
/// `within` is up.
fn wait_for_daemon(base: &str, data_dir: &Path, version: &str, within: Duration) -> Outcome {
    let deadline = Instant::now() + within;
    loop {
        let answered = health_version(base);
        let updating = install::updating(data_dir).is_some();
        match next(version, answered.as_deref(), updating) {
            Next::OpenNew => return Outcome::New,
            Next::OpenOld => return Outcome::Old(answered.unwrap_or_default()),
            Next::Wait if Instant::now() >= deadline => return Outcome::NotBack,
            Next::Wait => std::thread::sleep(POLL),
        }
    }
}

/// The helper's lines in `<data>/logs/app-update.log`, each with the time. A log that
/// cannot be written is left out: the update goes on.
struct Log(Option<File>);

impl Log {
    fn open(data_dir: &Path) -> Self {
        let folder = data_dir.join("logs");
        let file = std::fs::create_dir_all(&folder).ok().and_then(|()| {
            OpenOptions::new()
                .create(true)
                .append(true)
                .open(folder.join(LOG_FILE))
                .ok()
        });
        Self(file)
    }

    fn say(&mut self, line: &str) {
        if let Some(file) = &mut self.0 {
            let _ = writeln!(file, "{} {line}", utc_now());
        }
    }
}

/// The time now as `YYYY-MM-DD HH:MM:SS UTC`.
fn utc_now() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |since| since.as_secs());
    utc(seconds)
}

fn utc(seconds: u64) -> String {
    let (days, time) = (seconds / 86_400, seconds % 86_400);
    // Howard Hinnant's days-to-civil, for days since 1970-01-01.
    let z = days + 719_468;
    let era = z / 146_097;
    let doe = z % 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + u64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02} {:02}:{:02}:{:02} UTC",
        time / 3600,
        time % 3600 / 60,
        time % 60
    )
}

/// The helper's whole run, from the process's arguments after HELPER_ARG: the app's pid and
/// the new version. The exit code.
pub fn run(args: &[String]) -> i32 {
    let [pid, version] = args else {
        return 2;
    };
    let Ok(pid) = pid.parse::<u32>() else {
        return 2;
    };
    let env = env::process;
    let (Ok(data_dir), Ok(base), Ok(exe)) = (
        daemon::data_dir(&env),
        daemon::base_url(&env),
        std::env::current_exe(),
    ) else {
        return 1;
    };
    let mut log = Log::open(&data_dir);
    let Some(install) = app_swap::locate(&env, &exe) else {
        log.say("this Nest is no install: nothing to swap");
        return 1;
    };
    log.say(&format!(
        "Nest {pid} asked for {version}: waiting for it to quit"
    ));
    wait_for_exit(pid);
    let swapped = match wait_for_daemon(&base, &data_dir, version, NEW_APP_WAIT) {
        Outcome::Old(answered) => {
            log.say(&format!(
                "the daemon is back on {answered}: opening this app"
            ));
            false
        }
        Outcome::NotBack => {
            log.say(
                "the daemon is not back yet: opening this app, which follows the update itself",
            );
            false
        }
        Outcome::New if app_swap::open_elsewhere(&install) => {
            log.say("Nest is open already: it swaps itself");
            return 0;
        }
        Outcome::New => {
            log.say(&format!("the daemon answers on {version}"));
            let file = data_dir.join("daemon").join(version).join("app-file");
            let swap = file
                .to_str()
                .ok_or_else(|| "The app file's path is not text".to_owned())
                .and_then(|path| app_swap::app_file(path, &data_dir))
                .and_then(|file| app_swap::swap(&file, &install, &[]));
            match swap {
                Ok(()) => {
                    log.say("swapped in the new app: it opens as this helper ends");
                    true
                }
                Err(error) => {
                    log.say(&format!("{error}: keeping the old app"));
                    false
                }
            }
        }
    };
    if swapped {
        return 0;
    }
    match app_swap::reopen(&install, &[]) {
        Ok(()) => 0,
        Err(error) => {
            log.say(&error);
            1
        }
    }
}

#[cfg(unix)]
fn running(pid: u32) -> bool {
    let Ok(pid) = libc::pid_t::try_from(pid) else {
        return false;
    };
    // SAFETY: signal 0 only asks whether the process exists.
    unsafe { libc::kill(pid, 0) == 0 }
}

#[cfg(not(unix))]
fn running(_pid: u32) -> bool {
    false
}

fn wait_for_exit(pid: u32) {
    let deadline = Instant::now() + APP_WAIT;
    while running(pid) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(100));
    }
}

/// The version `/api/health` reports at `base` (`http://host:port`); None while it does not
/// answer. Plain HTTP on this machine, so no client library is needed.
fn health_version(base: &str) -> Option<String> {
    let host = base.strip_prefix("http://")?.split('/').next()?;
    let address = host.to_socket_addrs().ok()?.next()?;
    let mut stream = TcpStream::connect_timeout(&address, HEALTH_TIMEOUT).ok()?;
    stream.set_read_timeout(Some(HEALTH_TIMEOUT)).ok()?;
    stream.set_write_timeout(Some(HEALTH_TIMEOUT)).ok()?;
    let request =
        format!("GET /api/health HTTP/1.0\r\nHost: {host}\r\nAccept: application/json\r\n\r\n");
    stream.write_all(request.as_bytes()).ok()?;
    let mut response = Vec::new();
    stream.read_to_end(&mut response).ok()?;
    let response = String::from_utf8_lossy(&response);
    let (head, body) = response.split_once("\r\n\r\n")?;
    let status = head.lines().next()?.split_whitespace().nth(1)?;
    if status != "200" {
        return None;
    }
    let health: serde_json::Value = serde_json::from_str(body).ok()?;
    health.get("version")?.as_str().map(str::to_owned)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::TempDir;
    use std::net::TcpListener;

    #[test]
    fn only_the_new_version_opens_the_new_app() {
        assert_eq!(next("0.2.0", Some("0.2.0"), true), Next::OpenNew);
        assert_eq!(next("0.2.0", Some("0.2.0"), false), Next::OpenNew);
        // Regression: the old daemon, still answering just after the relaunch, is not the
        // update going back.
        assert_eq!(next("0.2.0", Some("0.1.0"), true), Next::Wait);
        assert_eq!(next("0.2.0", None, true), Next::Wait);
        assert_eq!(next("0.2.0", None, false), Next::Wait);
        assert_eq!(next("0.2.0", Some("0.1.0"), false), Next::OpenOld);
    }

    /// Regression (B130, fix 27): a new daemon that crashed and went back took 33 seconds in
    /// the VM, and the helper waited up to 2:30 with no Nest on screen, so the user opened it
    /// by hand. A daemon slower than the wait gets the old app back at once, which shows the
    /// update's progress and swaps itself later.
    #[test]
    fn a_slow_daemon_gets_the_old_app_back_at_once() {
        assert!(NEW_APP_WAIT <= Duration::from_secs(10));
        let dir = TempDir::new("after-update");
        let daemons = dir.path().join("daemon");
        std::fs::create_dir_all(&daemons).unwrap();
        std::fs::write(
            daemons.join("update.json"),
            r#"{"updating":{"from_version":"0.1.0","to_version":"0.2.0","started_at":"now"}}"#,
        )
        .unwrap();
        let old = serve_always("0.1.0");
        let started = Instant::now();
        let outcome = wait_for_daemon(&old, dir.path(), "0.2.0", Duration::from_secs(1));
        assert_eq!(outcome, Outcome::NotBack);
        assert!(started.elapsed() < Duration::from_secs(5));

        std::fs::write(daemons.join("update.json"), "{}").unwrap();
        let outcome = wait_for_daemon(&old, dir.path(), "0.2.0", Duration::from_secs(1));
        assert_eq!(outcome, Outcome::Old("0.1.0".to_owned()));
        let new = serve_always("0.2.0");
        let outcome = wait_for_daemon(&new, dir.path(), "0.2.0", Duration::from_secs(1));
        assert_eq!(outcome, Outcome::New);
    }

    #[test]
    fn the_helper_says_what_it_did_in_its_log() {
        let dir = TempDir::new("after-update");
        Log::open(dir.path()).say("the daemon is not back yet");
        Log::open(dir.path()).say("opened the new app");
        let text = std::fs::read_to_string(dir.path().join("logs").join(LOG_FILE)).unwrap();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 2);
        assert!(lines[0].ends_with(" UTC the daemon is not back yet"));
        assert!(lines[1].ends_with(" UTC opened the new app"));
        assert_eq!(utc(1_794_096_000), "2026-11-08 00:00:00 UTC");
        assert_eq!(utc(951_825_599), "2000-02-29 11:59:59 UTC");
    }

    /// A daemon that answers every request with `version`, for as long as the test runs.
    fn serve_always(version: &'static str) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        std::thread::spawn(move || {
            for mut stream in listener.incoming().flatten() {
                let mut request = [0u8; 1024];
                let _ = stream.read(&mut request);
                let body = format!("{{\"version\":\"{version}\"}}");
                let _ = stream.write_all(format!("HTTP/1.1 200 OK\r\n\r\n{body}").as_bytes());
            }
        });
        format!("http://127.0.0.1:{port}")
    }

    fn serve_once(response: &'static str) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0u8; 1024];
            let _ = stream.read(&mut request);
            stream.write_all(response.as_bytes()).unwrap();
        });
        format!("http://127.0.0.1:{port}")
    }

    #[test]
    fn the_daemons_version_is_read_from_its_health() {
        let base = serve_once(
            "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n\r\n\
             {\"status\":\"ok\",\"version\":\"0.2.0\",\"machine\":\"m\"}",
        );
        assert_eq!(health_version(&base).as_deref(), Some("0.2.0"));

        let failing = serve_once("HTTP/1.1 503 Service Unavailable\r\n\r\n{\"version\":\"0.2.0\"}");
        assert_eq!(health_version(&failing), None);

        let closed = TcpListener::bind("127.0.0.1:0").unwrap();
        let gone = format!("http://{}", closed.local_addr().unwrap());
        drop(closed);
        assert_eq!(health_version(&gone), None);
    }
}
