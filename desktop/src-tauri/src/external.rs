//! What Nest hands to the rest of the system: links for the default browser or mail app,
//! folders for the file manager, files the user saves.

use std::path::{Component, Path, PathBuf};

use tauri::Url;

/// A link the system may open: a web page or a mail address.
pub fn external_url(text: &str) -> Result<Url, String> {
    let url: Url = text.parse().map_err(|_| format!("Not a link: {text}"))?;
    let ok = match url.scheme() {
        "http" | "https" => url.host_str().is_some_and(|host| !host.is_empty()),
        "mailto" => true,
        _ => false,
    };
    if ok {
        Ok(url)
    } else {
        Err(format!("Only web and mail links open outside Nest: {text}"))
    }
}

/// `path` when it is in the user's home folder, with links resolved, so a link inside home
/// cannot lead elsewhere.
pub fn path_in_home(path: &str, home: &Path) -> Result<PathBuf, String> {
    let given = Path::new(path);
    if !given.is_absolute() {
        return Err(format!("Not a full path: {path}"));
    }
    let resolved = given
        .canonicalize()
        .map_err(|error| format!("Cannot open {path}: {error}"))?;
    let home = home
        .canonicalize()
        .map_err(|error| format!("Cannot find the home folder: {error}"))?;
    if resolved.starts_with(&home) {
        Ok(resolved)
    } else {
        Err(format!(
            "Only places in your home folder open from Nest: {path}"
        ))
    }
}

/// Makes the folder `path` when it is not there yet, such as the Claude skills folder on a
/// new machine, only where its nearest existing parent is in the home folder.
pub fn make_folder_in_home(path: &str, home: &Path) -> Result<(), String> {
    let given = Path::new(path);
    let plain = given
        .components()
        .all(|part| matches!(part, Component::RootDir | Component::Normal(_)));
    if !given.is_absolute() || !plain {
        return Err(format!("Not a full path: {path}"));
    }
    if given.is_dir() {
        return Ok(());
    }
    let existing = given
        .ancestors()
        .find(|folder| folder.exists())
        .ok_or_else(|| format!("Cannot open {path}"))?;
    path_in_home(&existing.to_string_lossy(), home)?;
    std::fs::create_dir_all(given).map_err(|error| format!("Cannot make {path}: {error}"))
}

/// The regular file `path` names inside the folder `root`, with `..` and links resolved, so
/// neither can lead out of it. `path` comes from a message and is untrusted; `root` must be
/// in the home folder too. Every refusal reads the same.
pub fn text_file_in(path: &str, root: &str, home: &Path) -> Result<PathBuf, String> {
    const NOT_FOUND: &str = "File not found";
    let folder = Path::new(root);
    if !folder.is_absolute() {
        return Err(NOT_FOUND.to_owned());
    }
    let folder = folder.canonicalize().map_err(|_| NOT_FOUND)?;
    let home = home.canonicalize().map_err(|_| NOT_FOUND)?;
    // Joining an absolute path gives that path, which has to pass the same check.
    let file = folder.join(path).canonicalize().map_err(|_| NOT_FOUND)?;
    let regular = file.metadata().is_ok_and(|found| found.is_file());
    if regular && file.starts_with(&folder) && folder.starts_with(&home) {
        Ok(file)
    } else {
        Err(NOT_FOUND.to_owned())
    }
}

/// The name for the save dialog: the last part of what the page suggested, never a path.
pub fn file_name(suggested: &str) -> String {
    let name = suggested
        .rsplit(['/', '\\'])
        .next()
        .unwrap_or_default()
        .trim();
    if name.is_empty() || name == "." || name == ".." {
        "Untitled".to_owned()
    } else {
        name.to_owned()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::TempDir;

    #[test]
    fn only_web_and_mail_links_leave_nest() {
        for ok in [
            "https://example.com/a?b",
            "http://example.com",
            "mailto:me@example.com",
        ] {
            assert!(external_url(ok).is_ok(), "{ok}");
        }
        for refused in [
            "file:///etc/passwd",
            "javascript:alert(1)",
            "tauri://localhost/desktop.html",
            "nest-artifact://localhost/x",
            "ssh://host",
            "/home/me/file",
            "",
        ] {
            assert!(external_url(refused).is_err(), "{refused}");
        }
    }

    #[cfg(unix)]
    #[test]
    fn only_paths_in_home_open_and_links_cannot_lead_out() {
        let root = TempDir::new("paths");
        let home = root.path().join("home");
        let project = home.join("project");
        let outside = root.path().join("elsewhere");
        std::fs::create_dir_all(&project).unwrap();
        std::fs::create_dir_all(&outside).unwrap();
        std::os::unix::fs::symlink(&outside, home.join("link")).unwrap();
        let text = |path: &Path| path.to_str().unwrap().to_owned();

        assert!(path_in_home(&text(&project), &home).is_ok());
        assert!(path_in_home(&text(&home), &home).is_ok());
        assert!(path_in_home(&text(&outside), &home).is_err());
        assert!(path_in_home(&text(&home.join("project/../../elsewhere")), &home).is_err());
        assert!(path_in_home(&text(&home.join("link")), &home).is_err());
        assert!(path_in_home("project", &home).is_err());
        assert!(path_in_home(&text(&home.join("missing")), &home).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn a_missing_folder_is_made_only_inside_home() {
        // Regression: Open folder did nothing for skills on a machine without the folder.
        let root = TempDir::new("make-folder");
        let home = root.path().join("home");
        std::fs::create_dir_all(&home).unwrap();
        std::os::unix::fs::symlink(root.path(), home.join("link")).unwrap();
        let text = |path: &Path| path.to_str().unwrap().to_owned();
        let skills = home.join(".claude/skills");

        assert_eq!(make_folder_in_home(&text(&skills), &home), Ok(()));
        assert!(skills.is_dir());
        assert!(path_in_home(&text(&skills), &home).is_ok());

        for refused in [
            text(&root.path().join("outside")),
            text(&home.join("link/outside")),
            text(&home.join("a/../../outside")),
            "relative/skills".to_owned(),
        ] {
            assert!(make_folder_in_home(&refused, &home).is_err(), "{refused}");
        }
        assert!(!root.path().join("outside").exists());
    }

    #[cfg(unix)]
    #[test]
    fn only_regular_files_inside_the_chats_folder_open() {
        let root = TempDir::new("text-files");
        let home = root.path().join("home");
        let project = home.join("project");
        let outside = home.join("secrets");
        std::fs::create_dir_all(project.join("docs")).unwrap();
        std::fs::create_dir_all(&outside).unwrap();
        std::fs::write(project.join("docs/plan.md"), "x").unwrap();
        std::fs::write(outside.join("key.md"), "x").unwrap();
        std::fs::write(root.path().join("out.md"), "x").unwrap();
        std::os::unix::fs::symlink(outside.join("key.md"), project.join("key.md")).unwrap();
        std::os::unix::fs::symlink(&outside, project.join("away")).unwrap();
        std::os::unix::fs::symlink(project.join("docs/plan.md"), project.join("near.md")).unwrap();
        let text = |path: &Path| path.to_str().unwrap().to_owned();
        let folder = text(&project);
        let plan = project.join("docs/plan.md").canonicalize().unwrap();

        assert_eq!(
            text_file_in("docs/plan.md", &folder, &home),
            Ok(plan.clone())
        );
        assert_eq!(
            text_file_in("./docs/../docs/plan.md", &folder, &home),
            Ok(plan.clone())
        );
        assert_eq!(text_file_in(&text(&plan), &folder, &home), Ok(plan.clone()));
        assert_eq!(text_file_in("near.md", &folder, &home), Ok(plan));

        for refused in [
            "../secrets/key.md",
            "docs/../../secrets/key.md",
            "key.md",
            "away/key.md",
            &text(&outside.join("key.md")),
            "/etc/passwd",
            "docs",
            ".",
            "missing.md",
        ] {
            assert!(text_file_in(refused, &folder, &home).is_err(), "{refused}");
        }
        assert!(text_file_in("docs/plan.md", "project", &home).is_err());
        assert!(text_file_in("out.md", &text(root.path()), &home).is_err());
        assert!(text_file_in("docs/plan.md", &text(&project.join("gone")), &home).is_err());
    }

    #[test]
    fn a_suggested_name_is_never_a_path() {
        assert_eq!(file_name("report.md"), "report.md");
        assert_eq!(file_name("../../.bashrc"), ".bashrc");
        assert_eq!(file_name("/etc/passwd"), "passwd");
        assert_eq!(file_name("a\\b.txt"), "b.txt");
        assert_eq!(file_name(".."), "Untitled");
        assert_eq!(file_name(""), "Untitled");
    }
}
