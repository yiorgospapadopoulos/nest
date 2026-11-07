//! The app follows the daemon (B130): the installer's AppImage is replaced by the file the
//! running daemon names, and Nest starts again from it. An update leaves the old app whole
//! until the new one is ready; a dev build is neither an AppImage nor unpacked, so it stays.

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use crate::env::{var, Env};

/// Where release/install.sh puts the app, and its copy unpacked for systems with no FUSE.
const APP_IMAGE: &str = "Nest.AppImage";
const APP_DIR: &str = "Nest.AppDir";
/// A release's app inside `<data>/daemon/<version>/` (daemon/src/nestd/updates/app.py).
const APP_FILE: &str = "app-file";
/// What `--appimage-extract` unpacks into.
const EXTRACTED: &str = "squashfs-root";
/// Set by the AppImage around the old app; the new one sets its own.
const APPIMAGE_VARS: &[&str] = &["APPIMAGE", "APPDIR", "ARGV0", "OWD", "LD_LIBRARY_PATH"];

/// Waits for this process to end, since a second Nest only brings the running one forward,
/// drops the app it ran from, then starts the new one. $1 pid, $2 program, $3 old folder.
const RELAUNCH: &str = r#"
tries=0
while [ "$tries" -lt 100 ] && kill -0 "$1" 2>/dev/null; do
    tries=$((tries + 1))
    sleep 0.1
done
[ -z "$3" ] || rm -rf "$3"
exec "$2"
"#;

#[derive(Debug, PartialEq, Eq)]
pub struct Install {
    image: PathBuf,
    // The unpacked copy beside the image, which then is what runs.
    app_dir: Option<PathBuf>,
}

impl Install {
    /// What starts the app: the unpacked copy's AppRun, else the image.
    pub fn program(&self) -> PathBuf {
        self.app_dir
            .as_ref()
            .map_or_else(|| self.image.clone(), |app_dir| app_dir.join("AppRun"))
    }
}

/// The install this process runs from; None for a dev build.
pub fn locate(env: Env, exe: &Path) -> Option<Install> {
    let image = match var(env, "APPIMAGE") {
        Some(image) => PathBuf::from(image),
        None => exe
            .ancestors()
            .find(|folder| folder.file_name().is_some_and(|name| name == APP_DIR))?
            .with_file_name(APP_IMAGE),
    };
    let app_dir = image.with_file_name(APP_DIR);
    Some(Install {
        app_dir: app_dir.is_dir().then_some(app_dir),
        image,
    })
}

/// `path` as a release's app file in the data folder. It comes from the page and is run, so
/// nothing else is accepted.
pub fn app_file(path: &str, data_dir: &Path) -> Result<PathBuf, String> {
    let file = PathBuf::from(path);
    let daemons = file.parent().and_then(Path::parent);
    if file.file_name().is_none_or(|name| name != APP_FILE)
        || daemons != Some(data_dir.join("daemon").as_path())
        || !file.is_file()
    {
        return Err(format!("Not an app of this install: {path}"));
    }
    Ok(file)
}

fn failed(what: &str, error: impl std::fmt::Display) -> String {
    format!("Could not {what}: {error}")
}

/// Puts the new app in place; the old one stays until the new one is complete. With an
/// unpacked copy, the old folder's name is returned, for removing once the app has ended.
fn replace(file: &Path, install: &Install) -> Result<Option<PathBuf>, String> {
    let temp = install.image.with_file_name(".Nest.AppImage.new");
    let result = replace_with(file, &temp, install);
    if result.is_err() {
        let _ = std::fs::remove_file(&temp);
    }
    result
}

fn replace_with(file: &Path, temp: &Path, install: &Install) -> Result<Option<PathBuf>, String> {
    std::fs::copy(file, temp).map_err(|error| failed("copy the new app", error))?;
    make_runnable(temp)?;
    let Some(app_dir) = &install.app_dir else {
        std::fs::rename(temp, &install.image).map_err(|error| failed("swap the app", error))?;
        return Ok(None);
    };
    let extracted = unpack(temp, app_dir)?;
    std::fs::rename(temp, &install.image).map_err(|error| failed("swap the app", error))?;
    let old = app_dir.with_file_name(format!("{APP_DIR}.old"));
    let _ = std::fs::remove_dir_all(&old);
    std::fs::rename(app_dir, &old).map_err(|error| failed("swap the app", error))?;
    std::fs::rename(&extracted, app_dir).map_err(|error| failed("swap the app", error))?;
    Ok(Some(old))
}

#[cfg(unix)]
fn make_runnable(path: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755))
        .map_err(|error| failed("make the new app runnable", error))
}

#[cfg(not(unix))]
fn make_runnable(_path: &Path) -> Result<(), String> {
    Ok(())
}

/// Unpacks `image` beside `app_dir`, which needs no FUSE; the unpacked folder.
fn unpack(image: &Path, app_dir: &Path) -> Result<PathBuf, String> {
    let folder = app_dir.parent().ok_or("The app has no folder")?;
    let extracted = folder.join(EXTRACTED);
    let _ = std::fs::remove_dir_all(&extracted);
    let status = Command::new(image)
        .arg("--appimage-extract")
        .current_dir(folder)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|error| failed("unpack the new app", error))?;
    if !status.success() || !extracted.join("AppRun").is_file() {
        let _ = std::fs::remove_dir_all(&extracted);
        return Err("Could not unpack the new app".to_owned());
    }
    Ok(extracted)
}

/// Leaves out what the old app set for itself (`own`) and its AppImage's variables, which a
/// new app works out again.
pub fn scrub(command: &mut Command, own: &[String]) {
    for name in own
        .iter()
        .map(String::as_str)
        .chain(APPIMAGE_VARS.iter().copied())
    {
        command.env_remove(name);
    }
}

fn relaunch(
    install: &Install,
    old: Option<&Path>,
    waiting_for: u32,
    scrub: &[String],
) -> Result<(), String> {
    let mut command = Command::new("sh");
    command
        .args(["-c", RELAUNCH, "nest-swap"])
        .arg(waiting_for.to_string())
        .arg(install.program())
        .arg(old.unwrap_or_else(|| Path::new("")))
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if let Some(folder) = install.image.parent() {
        command.current_dir(folder);
    }
    self::scrub(&mut command, scrub);
    command
        .spawn()
        .map(drop)
        .map_err(|error| failed("start the new app", error))
}

/// Leaves a waiting process to start the app as it is, once this process has ended.
pub fn reopen(install: &Install, scrub: &[String]) -> Result<(), String> {
    relaunch(install, None, std::process::id(), scrub)
}

/// Whether a Nest of this install runs besides this process, as one the user opened by hand
/// while a helper waited: never swapped under it, it swaps itself once it connects.
pub fn open_elsewhere(install: &Install) -> bool {
    let Ok(exe) = std::env::current_exe() else {
        return false;
    };
    exe.file_name().is_some_and(|name| {
        opened(
            Path::new("/proc"),
            install,
            std::process::id(),
            &name.to_string_lossy(),
        )
    })
}

/// A process in `proc` other than `own` that runs the app's program, `binary`, from this
/// install: from inside its unpacked copy, or with its AppImage named in its first
/// environment. Its AppImage runtime and anything else of the user's are not it.
fn opened(proc: &Path, install: &Install, own: u32, binary: &str) -> bool {
    let Ok(entries) = std::fs::read_dir(proc) else {
        return false;
    };
    let image = format!("APPIMAGE={}", install.image.display());
    entries.flatten().any(|entry| {
        let folder = entry.path();
        let is_other = entry
            .file_name()
            .to_str()
            .and_then(|name| name.parse::<u32>().ok())
            .is_some_and(|pid| pid != own);
        let Some(exe) = is_other
            .then(|| std::fs::read_link(folder.join("exe")).ok())
            .flatten()
        else {
            return false;
        };
        if exe.file_name().is_none_or(|name| name != binary) {
            return false;
        }
        install
            .app_dir
            .as_ref()
            .is_some_and(|app_dir| exe.starts_with(app_dir))
            || std::fs::read(folder.join("environ")).is_ok_and(|environ| {
                environ
                    .split(|byte| *byte == 0)
                    .any(|pair| pair == image.as_bytes())
            })
    })
}

/// Swaps to `file` and leaves a waiting process to start it; the caller then exits.
/// `scrub`: the variables Nest set for itself, which the new app must work out again.
pub fn swap(file: &Path, install: &Install, scrub: &[String]) -> Result<(), String> {
    let old = replace(file, install)?;
    relaunch(install, old.as_deref(), std::process::id(), scrub)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::env::fake;
    use crate::testing::TempDir;

    fn write(path: &Path, text: &str) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, text).unwrap();
        make_runnable(path).unwrap();
    }

    /// A stand-in AppImage: `--appimage-extract` leaves an AppRun holding `version`.
    fn image_script(version: &str) -> String {
        format!("#!/bin/sh\nmkdir -p {EXTRACTED}\necho {version} > {EXTRACTED}/AppRun\n")
    }

    #[test]
    fn a_dev_build_is_no_install() {
        let env = fake(&[]);
        assert_eq!(
            locate(&env, Path::new("/repo/target/debug/nest-desktop")),
            None
        );
    }

    #[test]
    fn the_install_is_found_from_the_appimage_or_the_unpacked_copy() {
        let dir = TempDir::new("swap");
        let image = dir.path().join(APP_IMAGE);
        let path = image.to_str().unwrap();
        let env = fake(&[("APPIMAGE", path)]);
        let exe = Path::new("/tmp/.mount_abc/usr/bin/nest-desktop");
        assert_eq!(
            locate(&env, exe),
            Some(Install {
                image: image.clone(),
                app_dir: None
            })
        );

        let app_dir = dir.path().join(APP_DIR);
        std::fs::create_dir(&app_dir).unwrap();
        let unpacked = fake(&[]);
        assert_eq!(
            locate(&unpacked, &app_dir.join("usr/bin/nest-desktop")),
            Some(Install {
                image,
                app_dir: Some(app_dir)
            })
        );
    }

    #[cfg(unix)]
    fn process(proc: &Path, pid: u32, exe: &Path, environ: &[&str]) {
        let folder = proc.join(pid.to_string());
        std::fs::create_dir_all(&folder).unwrap();
        std::os::unix::fs::symlink(exe, folder.join("exe")).unwrap();
        std::fs::write(folder.join("environ"), environ.join("\0")).unwrap();
    }

    /// A Nest the user opened while the helper waited is found, so the helper leaves it to
    /// swap itself; the helper itself, the AppImage's runtime and other apps are not one.
    #[cfg(unix)]
    #[test]
    fn a_nest_opened_by_hand_is_found_and_nothing_else() {
        let dir = TempDir::new("swap");
        let proc = dir.path().join("proc");
        let image = dir.path().join(APP_IMAGE);
        let packed = Install {
            image: image.clone(),
            app_dir: None,
        };
        let appimage = format!("APPIMAGE={}", image.display());
        let mounted = Path::new("/tmp/.mount_abc/usr/bin/nest-desktop");
        process(&proc, 10, mounted, &["HOME=/home/me", &appimage]);
        process(&proc, 11, &image, &[]);
        process(&proc, 12, Path::new("/usr/bin/bash"), &[&appimage]);
        assert!(!opened(&proc, &packed, 10, "nest-desktop"));
        process(&proc, 20, mounted, &[&appimage]);
        assert!(opened(&proc, &packed, 10, "nest-desktop"));

        let app_dir = dir.path().join(APP_DIR);
        let unpacked = Install {
            image,
            app_dir: Some(app_dir.clone()),
        };
        let other = dir.path().join("other");
        process(&other, 30, &app_dir.join("usr/bin/nest-desktop"), &[]);
        assert!(!opened(&other, &unpacked, 30, "nest-desktop"));
        process(&other, 31, &app_dir.join("usr/bin/nest-desktop"), &[]);
        assert!(opened(&other, &unpacked, 30, "nest-desktop"));
    }

    #[test]
    fn only_a_releases_app_file_is_accepted() {
        let dir = TempDir::new("swap");
        let file = dir.path().join("daemon/0.2.0").join(APP_FILE);
        write(&file, "app");
        assert_eq!(app_file(file.to_str().unwrap(), dir.path()), Ok(file));

        let other = dir.path().join("elsewhere/0.2.0").join(APP_FILE);
        write(&other, "app");
        let renamed = dir.path().join("daemon/0.2.0/run.sh");
        write(&renamed, "app");
        let gone = dir.path().join("daemon/0.3.0").join(APP_FILE);
        for path in [other, renamed, gone] {
            assert!(app_file(path.to_str().unwrap(), dir.path()).is_err());
        }
    }

    #[test]
    fn the_new_app_replaces_the_old_one_and_runs() {
        let dir = TempDir::new("swap");
        let image = dir.path().join(APP_IMAGE);
        write(&image, "old");
        let file = dir.path().join("new");
        write(&file, "new");
        let install = Install {
            image: image.clone(),
            app_dir: None,
        };

        assert_eq!(replace(&file, &install), Ok(None));

        assert_eq!(std::fs::read_to_string(&image).unwrap(), "new");
        assert_eq!(std::fs::read_dir(dir.path()).unwrap().count(), 2);
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(&image).unwrap().permissions().mode();
        assert_eq!(mode & 0o111, 0o111);
    }

    #[test]
    fn an_unpacked_copy_is_unpacked_again_first() {
        let dir = TempDir::new("swap");
        let image = dir.path().join(APP_IMAGE);
        write(&image, "old");
        let app_dir = dir.path().join(APP_DIR);
        write(&app_dir.join("AppRun"), "old");
        let file = dir.path().join("new");
        write(&file, &image_script("new"));
        let install = Install {
            image: image.clone(),
            app_dir: Some(app_dir.clone()),
        };

        let old = replace(&file, &install).unwrap().unwrap();

        assert_eq!(
            std::fs::read_to_string(app_dir.join("AppRun"))
                .unwrap()
                .trim(),
            "new"
        );
        assert_eq!(std::fs::read_to_string(old.join("AppRun")).unwrap(), "old");
        assert_eq!(
            std::fs::read_to_string(&image).unwrap(),
            image_script("new")
        );
    }

    #[test]
    fn the_new_app_starts_once_the_old_one_has_gone_and_its_old_folder_with_it() {
        let dir = TempDir::new("swap");
        let started = dir.path().join("started");
        let image = dir.path().join(APP_IMAGE);
        write(
            &image,
            &format!("#!/bin/sh\ntouch '{}'\n", started.display()),
        );
        let old = dir.path().join("Nest.AppDir.old");
        write(&old.join("AppRun"), "old");
        let install = Install {
            image,
            app_dir: None,
        };
        let mut ended = Command::new("true").spawn().unwrap();
        let pid = ended.id();
        ended.wait().unwrap();

        relaunch(&install, Some(&old), pid, &[]).unwrap();

        for _ in 0..50 {
            if started.exists() {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(100));
        }
        assert!(started.exists());
        assert!(!old.exists());
    }

    #[test]
    fn a_new_app_that_will_not_unpack_leaves_the_old_one_whole() {
        let dir = TempDir::new("swap");
        let image = dir.path().join(APP_IMAGE);
        write(&image, "old");
        let app_dir = dir.path().join(APP_DIR);
        write(&app_dir.join("AppRun"), "old");
        let file = dir.path().join("new");
        write(&file, "#!/bin/sh\nexit 1\n");
        let install = Install {
            image: image.clone(),
            app_dir: Some(app_dir.clone()),
        };

        assert!(replace(&file, &install).is_err());

        assert_eq!(std::fs::read_to_string(&image).unwrap(), "old");
        assert_eq!(
            std::fs::read_to_string(app_dir.join("AppRun")).unwrap(),
            "old"
        );
        assert!(!dir.path().join(".Nest.AppImage.new").exists());
        assert!(!dir.path().join(EXTRACTED).exists());
    }
}
