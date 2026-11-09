use std::path::PathBuf;

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

    #[test]
    fn outside_an_appimage_nothing_changes() {
        assert!(outside_app(&vars(&[
            ("LD_LIBRARY_PATH", "/opt/lib"),
            ("GTK_THEME", "x")
        ]))
        .is_empty());
    }
}
