//! Finds the local daemon: its address and this user's device token.

use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::env::{home, nest_var, var, Env};
use crate::platform;

pub const DATA_DIR_ENV: &str = "NEST_DATA_DIR";
pub const CONFIG_DIR_ENV: &str = "NEST_CONFIG_DIR";
pub const DAEMON_URL_ENV: &str = "NEST_DAEMON_URL";
/// The daemon's default `[server] port` (daemon/src/nestd/config/models.py).
pub const DEFAULT_PORT: u16 = 8765;

/// Stops `nestd serve` at start, written to daemon.log by the service (auth/secrets.py).
const SECRET_STORE_FAILURE: &str = "the secret store is not available";
/// The daemon's words for it (daemon/src/nestd/platform/linux.py).
const SECRET_STORE_HELP: &str = "Nest keeps its secrets in the Secret Service. Install \
    gnome-keyring (or another Secret Service provider, such as KeePassXC), unlock the login \
    keyring, then start Nest again.";
/// How much of the log's end counts: an old failure followed by a good start does not.
const LOG_TAIL_BYTES: u64 = 4096;
const LOG_TAIL_LINES: usize = 3;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct DaemonInfo {
    pub base_url: String,
    pub token: String,
}

pub fn locate(env: Env) -> Result<DaemonInfo, String> {
    let token = platform::read_local_token(&data_dir(env)?)?;
    Ok(DaemonInfo {
        base_url: base_url(env)?,
        token,
    })
}

/// What stops the daemon from starting, when the end of its log says so.
pub fn problem(env: Env) -> Option<String> {
    let log = log_tail(&data_dir(env).ok()?.join("logs").join("daemon.log"))?;
    log.lines()
        .rev()
        .filter(|line| !line.trim().is_empty())
        .take(LOG_TAIL_LINES)
        .any(|line| line.contains(SECRET_STORE_FAILURE))
        .then(|| SECRET_STORE_HELP.to_owned())
}

fn log_tail(path: &Path) -> Option<String> {
    let mut file = std::fs::File::open(path).ok()?;
    let length = file.metadata().ok()?.len();
    file.seek(SeekFrom::Start(length.saturating_sub(LOG_TAIL_BYTES)))
        .ok()?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes).ok()?;
    Some(String::from_utf8_lossy(&bytes).into_owned())
}

pub fn data_dir(env: Env) -> Result<PathBuf, String> {
    match nest_var(env, DATA_DIR_ENV) {
        Some(dir) => Ok(PathBuf::from(dir)),
        None => Ok(platform::default_data_dir(env, &home(env)?)),
    }
}

pub fn config_dir(env: Env) -> Result<PathBuf, String> {
    match nest_var(env, CONFIG_DIR_ENV) {
        Some(dir) => Ok(PathBuf::from(dir)),
        None => Ok(platform::default_config_dir(env, &home(env)?)),
    }
}

/// NEST_DAEMON_URL, else the daemon's own port on 127.0.0.1 (D014).
pub fn base_url(env: Env) -> Result<String, String> {
    if let Some(url) = var(env, DAEMON_URL_ENV) {
        return Ok(url.trim_end_matches('/').to_owned());
    }
    let settings =
        std::fs::read_to_string(config_dir(env)?.join("settings.toml")).unwrap_or_default();
    let port = server_port(&settings).unwrap_or(DEFAULT_PORT);
    Ok(format!("http://127.0.0.1:{port}"))
}

/// `port` in the `[server]` table of the daemon's settings.toml. A full TOML parser is
/// not needed for one integer key the daemon writes as `port = 8765`.
fn server_port(settings: &str) -> Option<u16> {
    let mut in_server = false;
    for line in settings.lines() {
        let line = line.split('#').next().unwrap_or_default().trim();
        if line.starts_with('[') {
            in_server = line == "[server]";
        } else if in_server {
            if let Some((key, value)) = line.split_once('=') {
                if key.trim() == "port" {
                    return value.trim().parse().ok();
                }
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::env::fake;

    #[test]
    fn data_dir_prefers_the_variable_then_xdg_then_home() {
        let home = [("HOME", "/home/me")];
        let env = fake(&home);
        assert_eq!(
            data_dir(&env).unwrap(),
            PathBuf::from("/home/me/.local/share/nest")
        );

        let xdg = fake(&[("HOME", "/home/me"), ("XDG_DATA_HOME", "/data")]);
        assert_eq!(data_dir(&xdg).unwrap(), PathBuf::from("/data/nest"));

        // The XDG spec says to ignore a relative path.
        let relative = fake(&[("HOME", "/home/me"), ("XDG_DATA_HOME", "data")]);
        assert_eq!(
            data_dir(&relative).unwrap(),
            PathBuf::from("/home/me/.local/share/nest")
        );

        let legacy = fake(&[
            ("HOME", "/home/me"),
            ("XDG_DATA_HOME", "/data"),
            ("HARNESS_DATA_DIR", "/old"),
        ]);
        assert_eq!(data_dir(&legacy).unwrap(), PathBuf::from("/old"));

        let chosen = fake(&[
            ("HOME", "/home/me"),
            ("XDG_DATA_HOME", "/data"),
            ("HARNESS_DATA_DIR", "/old"),
            ("NEST_DATA_DIR", "/test-daemon"),
        ]);
        assert_eq!(data_dir(&chosen).unwrap(), PathBuf::from("/test-daemon"));
    }

    #[test]
    fn only_the_end_of_the_log_says_the_secret_store_stopped_the_daemon() {
        let dir = crate::testing::TempDir::new("daemon");
        let data = dir.path().to_str().unwrap();
        let env = fake(&[("NEST_DATA_DIR", data)]);
        assert_eq!(problem(&env), None);

        let failure = "nestd: the secret store is not available (no bus). Nest keeps its ...\n";
        std::fs::create_dir(dir.path().join("logs")).unwrap();
        let log = dir.path().join("logs/daemon.log");
        std::fs::write(&log, format!("INFO starting\n{failure}")).unwrap();
        assert_eq!(problem(&env).as_deref(), Some(SECRET_STORE_HELP));

        std::fs::write(&log, format!("{failure}INFO a\nINFO b\nINFO c\nINFO d\n")).unwrap();
        assert_eq!(problem(&env), None);
    }

    #[test]
    fn base_url_uses_the_variable_else_the_daemon_port() {
        let dir = crate::testing::TempDir::new("daemon");
        let config = dir.path().to_str().unwrap();
        let env = fake(&[("NEST_CONFIG_DIR", config)]);
        assert_eq!(base_url(&env).unwrap(), "http://127.0.0.1:8765");

        std::fs::write(
            dir.path().join("settings.toml"),
            "[usage]\nport = 1\n\n[server]\n# moved\nport = 9123  # test daemon\n",
        )
        .unwrap();
        assert_eq!(base_url(&env).unwrap(), "http://127.0.0.1:9123");

        let chosen = fake(&[
            ("NEST_CONFIG_DIR", config),
            ("NEST_DAEMON_URL", "http://127.0.0.1:7000/"),
        ]);
        assert_eq!(base_url(&chosen).unwrap(), "http://127.0.0.1:7000");
    }
}
