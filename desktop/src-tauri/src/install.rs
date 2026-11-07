//! A released install, read from Nest's data folder by the app itself, since the daemon may
//! be down (B130): an update under way, the address the install came from, and the `nest`
//! command that removes it.

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use serde::{Deserialize, Serialize};

use crate::env::{var, Env};

/// daemon/src/nestd/updates/app.py's state file in `<data>/daemon/`.
const UPDATE_STATE: &str = "update.json";
/// Written by release/install.sh (daemon/src/nestd/release.py).
const RELEASE_URL_FILE: &str = "release-url";
const RELEASE_URL_ENV: &str = "NEST_RELEASE_URL";
pub const DEFAULT_RELEASE_URL: &str =
    "https://github.com/yiorgospapadopoulos/nest/releases/latest/download";

/// A relaunch under way: the watcher clears it once the new version answers or is undone.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Updating {
    pub from_version: String,
    pub to_version: String,
    pub started_at: String,
}

#[derive(Debug, PartialEq, Eq, Serialize)]
pub struct InstallState {
    pub updating: Option<Updating>,
    pub release_url: String,
    /// Whether this is a released install, which `nest uninstall` can remove.
    pub released: bool,
}

pub fn state(env: Env, data_dir: &Path) -> InstallState {
    InstallState {
        updating: updating(data_dir),
        release_url: release_url(env, data_dir),
        released: nest_command(data_dir).is_ok(),
    }
}

pub fn updating(data_dir: &Path) -> Option<Updating> {
    #[derive(Deserialize)]
    struct File {
        #[serde(default)]
        updating: Option<Updating>,
    }
    let text = std::fs::read_to_string(data_dir.join("daemon").join(UPDATE_STATE)).ok()?;
    serde_json::from_str::<File>(&text).ok()?.updating
}

/// As the daemon's release_url: the variable, else the file, else GitHub.
fn release_url(env: Env, data_dir: &Path) -> String {
    let chosen = var(env, RELEASE_URL_ENV).or_else(|| {
        std::fs::read_to_string(data_dir.join(RELEASE_URL_FILE))
            .ok()
            .map(|text| text.trim().to_owned())
            .filter(|text| !text.is_empty())
    });
    chosen
        .as_deref()
        .unwrap_or(DEFAULT_RELEASE_URL)
        .trim_end_matches('/')
        .to_owned()
}

/// `<data>/daemon/current/bin/nest`, with its links resolved, only while it stays inside
/// the data folder's `daemon`: a checkout has none.
pub fn nest_command(data_dir: &Path) -> Result<PathBuf, String> {
    let daemons = data_dir.join("daemon");
    let not_released = || "This Nest is not a released install".to_owned();
    let command = daemons
        .join("current/bin/nest")
        .canonicalize()
        .map_err(|_| not_released())?;
    let daemons = daemons.canonicalize().map_err(|_| not_released())?;
    if command.starts_with(&daemons) && command.is_file() {
        Ok(command)
    } else {
        Err(not_released())
    }
}

/// Starts `nest uninstall` in a session of its own, so it outlives the app and the service
/// it removes; the caller quits next.
pub fn uninstall(data_dir: &Path, delete_data: bool, scrub: &[String]) -> Result<(), String> {
    let mut command = Command::new(nest_command(data_dir)?);
    command.arg("uninstall");
    if delete_data {
        command.arg("--delete-data");
    }
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    for name in scrub {
        command.env_remove(name);
    }
    detach(&mut command);
    command
        .spawn()
        .map(drop)
        .map_err(|error| format!("Could not start the uninstall: {error}"))
}

/// The process gets a session of its own, so the end of Nest's does not end it.
#[cfg(unix)]
pub fn detach(command: &mut Command) {
    use std::os::unix::process::CommandExt;
    // SAFETY: setsid is async-signal-safe and touches no memory of the parent.
    unsafe {
        command.pre_exec(|| {
            if libc::setsid() == -1 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
}

#[cfg(not(unix))]
pub fn detach(_command: &mut Command) {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::env::fake;
    use crate::testing::TempDir;

    fn write(path: &Path, text: &str) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, text).unwrap();
    }

    #[test]
    fn an_update_under_way_is_read_from_the_daemons_file() {
        let dir = TempDir::new("install");
        assert_eq!(updating(dir.path()), None);

        let file = dir.path().join("daemon").join(UPDATE_STATE);
        write(&file, r#"{"ready": null, "refused": [], "updating": null}"#);
        assert_eq!(updating(dir.path()), None);

        write(
            &file,
            r#"{"updating": {"from_version": "0.1.0", "to_version": "0.1.1",
                "started_at": "2026-11-07T10:00:00.123456+00:00"}, "previous": "0.1.0"}"#,
        );
        assert_eq!(
            updating(dir.path()),
            Some(Updating {
                from_version: "0.1.0".to_owned(),
                to_version: "0.1.1".to_owned(),
                started_at: "2026-11-07T10:00:00.123456+00:00".to_owned(),
            })
        );
    }

    #[test]
    fn the_release_address_is_the_one_the_install_came_from() {
        let dir = TempDir::new("install");
        let none = fake(&[]);
        assert_eq!(release_url(&none, dir.path()), DEFAULT_RELEASE_URL);

        write(
            &dir.path().join(RELEASE_URL_FILE),
            "http://192.168.64.1:41051/\n",
        );
        assert_eq!(release_url(&none, dir.path()), "http://192.168.64.1:41051");

        let chosen = fake(&[(RELEASE_URL_ENV, "http://127.0.0.1:41055")]);
        assert_eq!(release_url(&chosen, dir.path()), "http://127.0.0.1:41055");
    }

    #[test]
    fn only_a_nest_command_inside_the_data_folder_counts() {
        let dir = TempDir::new("install");
        let data = dir.path().join("data");
        std::fs::create_dir_all(data.join("daemon")).unwrap();
        assert!(nest_command(&data).is_err());

        // `current` pointing out of the data folder is not this install's.
        let elsewhere = dir.path().join("elsewhere");
        write(&elsewhere.join("bin/nest"), "#!/bin/sh\n");
        std::os::unix::fs::symlink(&elsewhere, data.join("daemon/current")).unwrap();
        assert!(nest_command(&data).is_err());

        std::fs::remove_file(data.join("daemon/current")).unwrap();
        let release = data.join("daemon/0.1.1");
        write(&release.join("bin/nest"), "#!/bin/sh\n");
        std::os::unix::fs::symlink(&release, data.join("daemon/current")).unwrap();
        assert_eq!(
            nest_command(&data).unwrap(),
            release.join("bin/nest").canonicalize().unwrap()
        );
    }

    #[test]
    fn uninstall_deletes_the_data_only_when_asked() {
        use std::os::unix::fs::PermissionsExt;
        let dir = TempDir::new("install");
        let asked = dir.path().join("asked");
        let release = dir.path().join("daemon/0.1.1");
        let nest = release.join("bin/nest");
        write(
            &nest,
            &format!("#!/bin/sh\necho \"$@\" >> '{}'\n", asked.display()),
        );
        std::fs::set_permissions(&nest, std::fs::Permissions::from_mode(0o755)).unwrap();
        std::os::unix::fs::symlink(&release, dir.path().join("daemon/current")).unwrap();

        let run = |delete_data: bool| {
            let before = std::fs::read_to_string(&asked).unwrap_or_default().len();
            uninstall(dir.path(), delete_data, &[]).unwrap();
            for _ in 0..50 {
                if std::fs::read_to_string(&asked).unwrap_or_default().len() > before {
                    break;
                }
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
        };
        run(false);
        run(true);

        assert_eq!(
            std::fs::read_to_string(&asked).unwrap(),
            "uninstall\nuninstall --delete-data\n"
        );
    }
}
