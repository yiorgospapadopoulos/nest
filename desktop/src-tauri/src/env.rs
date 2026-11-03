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
