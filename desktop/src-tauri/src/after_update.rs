//! Relaunch to update with a new app opens it once (B130): the app starts this helper and
//! quits. The helper waits for the daemon to come back, then swaps to the new app and opens
//! it, or opens the old one as it is when the update went back. Without it the old app
//! would load again after the daemon's restart, only to quit for the swap.

use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use crate::app_swap::{self, Install};
use crate::{daemon, env, install};

/// The first argument that makes a Nest process this helper, with no window.
pub const HELPER_ARG: &str = "--nest-after-update";
/// How long the new daemon gets, a little more than the watcher's trial of a hung one.
const DAEMON_WAIT: Duration = Duration::from_secs(150);
const APP_WAIT: Duration = Duration::from_secs(10);
const POLL: Duration = Duration::from_millis(500);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(2);

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
    let Some(install) = app_swap::locate(&env, &exe) else {
        return 1;
    };
    wait_for_exit(pid);
    let deadline = Instant::now() + DAEMON_WAIT;
    let open_new = loop {
        let answered = health_version(&base);
        match next(
            version,
            answered.as_deref(),
            install::updating(&data_dir).is_some(),
        ) {
            Next::OpenNew => break true,
            Next::OpenOld => break false,
            Next::Wait if Instant::now() >= deadline => break false,
            Next::Wait => std::thread::sleep(POLL),
        }
    };
    let swapped = open_new
        && data_dir
            .join("daemon")
            .join(version)
            .join("app-file")
            .to_str()
            .and_then(|path| app_swap::app_file(path, &data_dir).ok())
            .is_some_and(|file| app_swap::swap(&file, &install, &[]).is_ok());
    if swapped || app_swap::reopen(&install, &[]).is_ok() {
        0
    } else {
        1
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
