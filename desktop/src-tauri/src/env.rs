use std::path::PathBuf;
use std::process::Command;
use std::sync::OnceLock;

/// Reads an environment variable; tests pass their own instead of the process's.
pub type Env<'a> = &'a dyn Fn(&str) -> Option<String>;

pub fn process(name: &str) -> Option<String> {
    std::env::var(name).ok()
}

/// The variable's value; None when it is unset or empty.
pub fn var(env: Env, name: &str) -> Option<String> {
    env(name).filter(|value| !value.is_empty())
}

/// A `NEST_*` variable, or its name from before the rename (`HARNESS_*`), as the daemon
/// reads them.
pub fn nest_var(env: Env, name: &str) -> Option<String> {
    var(env, name).or_else(|| {
        let legacy = format!("HARNESS_{}", name.trim_start_matches("NEST_"));
        var(env, &legacy)
    })
}

pub fn home(env: Env) -> Result<PathBuf, String> {
    var(env, "HOME")
        .map(PathBuf::from)
        .ok_or_else(|| "HOME is not set".to_owned())
}

#[cfg(test)]
pub fn fake(vars: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
    let vars: Vec<(String, String)> = vars
        .iter()
        .map(|(name, value)| (name.to_string(), value.to_string()))
        .collect();
    move |name| {
        vars.iter()
            .find(|(key, _)| key == name)
            .map(|(_, value)| value.clone())
    }
}

/// Set by the AppImage around the app; a program the app starts is not inside it.
const APPIMAGE_OWN: &[&str] = &["APPIMAGE", "APPDIR", "ARGV0", "OWD", "GTK_THEME"];

/// What the user's shell and the programs Nest starts get back from the AppImage's start
/// scripts, which point library, plugin and data paths into the app's folder (`APPDIR`):
/// each variable to change, with None to remove it. A list keeps its entries outside the
/// folder; the system tools a terminal runs would otherwise load the app's libraries.
pub fn outside_app(vars: &[(String, String)]) -> Vec<(String, Option<String>)> {
    let Some(appdir) = vars
        .iter()
        .find(|(name, _)| name == "APPDIR")
        .map(|(_, value)| value.trim_end_matches('/').to_owned())
        .filter(|dir| !dir.is_empty())
    else {
        return Vec::new();
    };
    let inside = |entry: &str| entry == appdir || entry.starts_with(&format!("{appdir}/"));
    vars.iter()
        .filter_map(|(name, value)| {
            if APPIMAGE_OWN.contains(&name.as_str()) {
                return Some((name.clone(), None));
            }
            if !value.split(':').any(inside) {
                return None;
            }
            let kept: Vec<&str> = value
                .split(':')
                .filter(|entry| !entry.is_empty() && !inside(entry))
                .collect();
            Some((name.clone(), (!kept.is_empty()).then(|| kept.join(":"))))
        })
        .collect()
}

/// The variables Nest set for itself before GTK started (lib.rs, `prepare`).
static OWN: OnceLock<Vec<String>> = OnceLock::new();

/// Remembers the variables Nest set for itself, which no program it starts gets.
pub fn set_own(names: Vec<String>) {
    let _ = OWN.set(names);
}

/// What every program Nest starts gets changed in its environment (B159 R18): Nest's own
/// variables (`own`) removed, and the AppImage's paths taken out (`outside_app`), each with
/// None to remove it. Without this a newer system's tools load the app's older libraries.
pub fn for_programs(own: &[String], vars: &[(String, String)]) -> Vec<(String, Option<String>)> {
    let mut changes: Vec<(String, Option<String>)> =
        own.iter().map(|name| (name.clone(), None)).collect();
    for (name, value) in outside_app(vars) {
        if !own.contains(&name) {
            changes.push((name, value));
        }
    }
    changes
}

/// `for_programs` for this process as it is now.
pub fn program_changes() -> Vec<(String, Option<String>)> {
    let vars: Vec<(String, String)> = std::env::vars_os()
        .filter_map(|(name, value)| Some((name.into_string().ok()?, value.into_string().ok()?)))
        .collect();
    for_programs(OWN.get().map_or(&[], Vec::as_slice), &vars)
}

/// `command` with the user's own environment rather than the app's (`program_changes`).
pub fn outside(command: &mut Command) -> &mut Command {
    apply(command, &program_changes())
}

fn apply<'a>(command: &'a mut Command, changes: &[(String, Option<String>)]) -> &'a mut Command {
    for (name, value) in changes {
        match value {
            Some(value) => command.env(name, value),
            None => command.env_remove(name),
        };
    }
    command
}

#[cfg(test)]
mod tests {
    use super::*;

    fn vars(pairs: &[(&str, &str)]) -> Vec<(String, String)> {
        pairs
            .iter()
            .map(|(name, value)| (name.to_string(), value.to_string()))
            .collect()
    }

    // Regression (B157, Ubuntu 26.04): the Linux app's terminal printed "libsystemd.so.0:
    // version LIBSYSTEMD_254 not found (required by basename)" at every start: the shell
    // got the AppImage's LD_LIBRARY_PATH and loaded the app's own libraries.
    #[test]
    fn a_shell_gets_none_of_the_app_s_own_folder() {
        let app = "/home/u/.local/share/nest/app/Nest.AppDir";
        let changes = outside_app(&vars(&[
            ("APPDIR", app),
            ("LD_LIBRARY_PATH", &format!("{app}/usr/lib/:{app}/lib/:")),
            (
                "XDG_DATA_DIRS",
                &format!("{app}/usr/share:/usr/share:/var/lib/snapd/desktop"),
            ),
            ("GIO_MODULE_DIR", &format!("{app}//usr/lib/gio/modules")),
            ("GTK_THEME", "Adwaita:light"),
            ("PATH", "/usr/bin:/bin"),
            ("HOME", "/home/u"),
        ]));

        assert!(changes.contains(&("APPDIR".to_owned(), None)));
        assert!(changes.contains(&("LD_LIBRARY_PATH".to_owned(), None)));
        assert!(changes.contains(&("GIO_MODULE_DIR".to_owned(), None)));
        assert!(changes.contains(&("GTK_THEME".to_owned(), None)));
        assert!(changes.contains(&(
            "XDG_DATA_DIRS".to_owned(),
            Some("/usr/share:/var/lib/snapd/desktop".to_owned())
        )));
        assert!(!changes
            .iter()
            .any(|(name, _)| name == "PATH" || name == "HOME"));
    }

    // Regression (B159 R18): only the terminal got this; xdg-open, systemctl, the text
    // editor and `nest uninstall` ran with the AppImage's LD_LIBRARY_PATH and Nest's GDK_*.
    #[test]
    fn a_program_nest_starts_gets_neither_nest_s_variables_nor_the_app_s_libraries() {
        let app = "/tmp/.mount_NestAb";
        let own = vec!["GDK_BACKEND".to_owned(), "GDK_SCALE".to_owned()];
        let changes = for_programs(
            &own,
            &vars(&[
                ("APPDIR", app),
                ("APPIMAGE", "/home/u/Nest.AppImage"),
                ("LD_LIBRARY_PATH", &format!("{app}/usr/lib")),
                ("XDG_DATA_DIRS", &format!("{app}/usr/share:/usr/share")),
                ("GDK_BACKEND", "x11"),
                ("GDK_SCALE", "2"),
                ("PATH", "/usr/bin:/bin"),
            ]),
        );
        let mut command = Command::new("true");
        apply(&mut command, &changes);
        let mut got: Vec<(String, Option<String>)> = command
            .get_envs()
            .map(|(name, value)| {
                (
                    name.to_string_lossy().into_owned(),
                    value.map(|value| value.to_string_lossy().into_owned()),
                )
            })
            .collect();
        got.sort();

        assert_eq!(
            got,
            [
                ("APPDIR".to_owned(), None),
                ("APPIMAGE".to_owned(), None),
                ("GDK_BACKEND".to_owned(), None),
                ("GDK_SCALE".to_owned(), None),
                ("LD_LIBRARY_PATH".to_owned(), None),
                ("XDG_DATA_DIRS".to_owned(), Some("/usr/share".to_owned())),
            ]
        );
    }

    #[test]
    fn outside_an_appimage_nothing_changes() {
        assert!(outside_app(&vars(&[
            ("LD_LIBRARY_PATH", "/opt/lib"),
            ("GTK_THEME", "x")
        ]))
        .is_empty());
    }
}
