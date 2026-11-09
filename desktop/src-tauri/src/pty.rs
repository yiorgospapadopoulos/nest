//! Terminals: the user's login shell in a pseudo-terminal, its output read on a thread
//! of its own and handed out as text.

use std::collections::HashMap;
use std::io::{Read, Write};
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::thread;

use portable_pty::{native_pty_system, ChildKiller, CommandBuilder, MasterPty, PtySize};

type Shared<T> = Arc<Mutex<T>>;

struct Session {
    master: Box<dyn MasterPty + Send>,
    writer: Shared<Box<dyn Write + Send>>,
    killer: Box<dyn ChildKiller + Send + Sync>,
}

pub struct Ptys {
    sessions: Shared<HashMap<String, Session>>,
    /// Variables Nest set for itself (such as GDK_BACKEND), kept out of the shell.
    scrub: Vec<String>,
    /// What the AppImage pointed into the app's folder, put back for the shell.
    outside_app: Vec<(String, Option<String>)>,
}

/// Ids name events (`pty://<id>`), so they keep to the characters event names allow.
fn valid_id(id: &str) -> bool {
    (1..=64).contains(&id.len())
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

fn size(cols: u16, rows: u16) -> PtySize {
    PtySize {
        rows: rows.max(1),
        cols: cols.max(1),
        pixel_width: 0,
        pixel_height: 0,
    }
}

impl Ptys {
    pub fn new(scrub: Vec<String>) -> Self {
        let vars: Vec<(String, String)> = std::env::vars().collect();
        Self {
            sessions: Arc::default(),
            scrub,
            outside_app: crate::env::outside_app(&vars),
        }
    }

    /// The user's shell (from $SHELL or the user database) started as a login shell.
    pub fn login_shell(&self, cwd: &Path) -> CommandBuilder {
        let mut command = CommandBuilder::new_default_prog();
        command.cwd(cwd);
        command.env("TERM", "xterm-256color");
        command.env("COLORTERM", "truecolor");
        command
    }

    /// Starts `command` under the id the caller chose; `output` gets every chunk it
    /// prints and `exit` its exit code once the terminal closes.
    pub fn spawn(
        &self,
        id: &str,
        mut command: CommandBuilder,
        cols: u16,
        rows: u16,
        mut output: impl FnMut(String) + Send + 'static,
        exit: impl FnOnce(u32) + Send + 'static,
    ) -> Result<(), String> {
        if !valid_id(id) {
            return Err(format!(
                "Not a terminal id: {id:?} (letters, digits, - and _)"
            ));
        }
        let mut sessions = self.sessions.lock().unwrap();
        if sessions.contains_key(id) {
            return Err(format!("Terminal {id} is already open"));
        }
        for name in &self.scrub {
            command.env_remove(name);
        }
        for (name, value) in &self.outside_app {
            match value {
                Some(value) => command.env(name, value),
                None => command.env_remove(name),
            }
        }
        let pair = native_pty_system()
            .openpty(size(cols, rows))
            .map_err(opening)?;
        let mut child = pair.slave.spawn_command(command).map_err(opening)?;
        // Only the child keeps the terminal's other end open, so its exit ends the reads.
        drop(pair.slave);
        let mut reader = pair.master.try_clone_reader().map_err(opening)?;
        let writer = pair.master.take_writer().map_err(opening)?;
        sessions.insert(
            id.to_owned(),
            Session {
                killer: child.clone_killer(),
                master: pair.master,
                writer: Arc::new(Mutex::new(writer)),
            },
        );
        drop(sessions);

        let sessions = Arc::clone(&self.sessions);
        let id = id.to_owned();
        thread::spawn(move || {
            let mut text = Utf8Stream::default();
            let mut buffer = [0u8; 16 * 1024];
            // Linux reports the closed terminal as an error (EIO), not as end of file.
            while let Ok(read) = reader.read(&mut buffer) {
                if read == 0 {
                    break;
                }
                let chunk = text.push(&buffer[..read]);
                if !chunk.is_empty() {
                    output(chunk);
                }
            }
            let rest = text.finish();
            if !rest.is_empty() {
                output(rest);
            }
            sessions.lock().unwrap().remove(&id);
            let code = child.wait().map(|status| status.exit_code()).unwrap_or(1);
            exit(code);
        });
        Ok(())
    }

    pub fn write(&self, id: &str, data: &[u8]) -> Result<(), String> {
        // Writing can block while the shell is busy, so other terminals are not held up.
        let writer = Arc::clone(&self.session(id, |session| Arc::clone(&session.writer))?);
        let mut writer = writer.lock().unwrap();
        writer
            .write_all(data)
            .and_then(|()| writer.flush())
            .map_err(|error| format!("Could not write to terminal {id}: {error}"))
    }

    pub fn resize(&self, id: &str, cols: u16, rows: u16) -> Result<(), String> {
        self.session(id, |session| session.master.resize(size(cols, rows)))?
            .map_err(|error| format!("Could not resize terminal {id}: {error}"))
    }

    /// Ends the shell; its exit still arrives through `exit`.
    pub fn kill(&self, id: &str) -> Result<(), String> {
        self.session(id, |session| session.killer.kill())?
            .map_err(|error| format!("Could not stop terminal {id}: {error}"))
    }

    fn session<T>(&self, id: &str, use_it: impl FnOnce(&mut Session) -> T) -> Result<T, String> {
        let mut sessions = self.sessions.lock().unwrap();
        let session = sessions
            .get_mut(id)
            .ok_or_else(|| format!("No terminal {id}"))?;
        Ok(use_it(session))
    }
}

fn opening(error: impl std::fmt::Display) -> String {
    format!("Could not open a terminal: {error}")
}

/// Decodes a byte stream as UTF-8 across read boundaries: a character split between two
/// reads comes out whole; bytes that are not UTF-8 become U+FFFD.
#[derive(Default)]
struct Utf8Stream {
    pending: Vec<u8>,
}

impl Utf8Stream {
    fn push(&mut self, bytes: &[u8]) -> String {
        self.pending.extend_from_slice(bytes);
        let mut text = String::new();
        let mut rest: &[u8] = &self.pending;
        loop {
            match std::str::from_utf8(rest) {
                Ok(valid) => {
                    text.push_str(valid);
                    rest = &[];
                    break;
                }
                Err(error) => {
                    let (valid, after) = rest.split_at(error.valid_up_to());
                    text.push_str(std::str::from_utf8(valid).unwrap_or_default());
                    match error.error_len() {
                        Some(bad) => {
                            text.push(char::REPLACEMENT_CHARACTER);
                            rest = &after[bad..];
                        }
                        None => {
                            rest = after;
                            break;
                        }
                    }
                }
            }
        }
        self.pending = rest.to_vec();
        text
    }

    fn finish(&mut self) -> String {
        let rest = std::mem::take(&mut self.pending);
        String::from_utf8_lossy(&rest).into_owned()
    }
}

#[cfg(test)]
mod tests {
    use std::sync::mpsc;
    use std::time::{Duration, Instant};

    use super::*;

    const WAIT: Duration = Duration::from_secs(10);

    struct Terminal {
        output: mpsc::Receiver<String>,
        exit: mpsc::Receiver<u32>,
        seen: String,
    }

    impl Terminal {
        fn wait_for(&mut self, text: &str) {
            let deadline = Instant::now() + WAIT;
            while !self.seen.contains(text) {
                let left = deadline.saturating_duration_since(Instant::now());
                match self.output.recv_timeout(left) {
                    Ok(chunk) => self.seen.push_str(&chunk),
                    Err(_) => panic!("never printed {text:?}; got {:?}", self.seen),
                }
            }
        }
    }

    fn open_sh(ptys: &Ptys, id: &str) -> Terminal {
        let (output_tx, output) = mpsc::channel();
        let (exit_tx, exit) = mpsc::channel();
        let mut sh = CommandBuilder::new("/bin/sh");
        sh.cwd(std::env::temp_dir());
        ptys.spawn(
            id,
            sh,
            80,
            24,
            move |chunk| {
                let _ = output_tx.send(chunk);
            },
            move |code| {
                let _ = exit_tx.send(code);
            },
        )
        .unwrap();
        Terminal {
            output,
            exit,
            seen: String::new(),
        }
    }

    #[test]
    fn a_shell_runs_what_is_typed_and_reports_its_exit() {
        let ptys = Ptys::new(Vec::new());
        let mut terminal = open_sh(&ptys, "t1");

        ptys.resize("t1", 120, 40).unwrap();
        // The typed line is echoed as is; only the shell's answer contains "nest-2".
        ptys.write("t1", b"echo nest-$((1+1))\n").unwrap();
        terminal.wait_for("nest-2");
        ptys.write("t1", b"exit 3\n").unwrap();

        assert_eq!(terminal.exit.recv_timeout(WAIT).unwrap(), 3);
        assert!(
            ptys.write("t1", b"x").is_err(),
            "a closed terminal is forgotten"
        );
    }

    #[test]
    fn killing_a_terminal_ends_it() {
        let ptys = Ptys::new(Vec::new());
        let terminal = open_sh(&ptys, "t2");

        ptys.kill("t2").unwrap();

        terminal.exit.recv_timeout(WAIT).unwrap();
    }

    #[test]
    fn ids_are_unique_and_safe_for_event_names() {
        let ptys = Ptys::new(Vec::new());
        let _terminal = open_sh(&ptys, "same");
        let spawn =
            |id: &str| ptys.spawn(id, CommandBuilder::new("/bin/sh"), 80, 24, |_| {}, |_| {});

        assert!(spawn("same").is_err());
        assert!(spawn("a/b").is_err());
        assert!(spawn("").is_err());
        ptys.kill("same").unwrap();
    }

    #[test]
    fn nest_variables_stay_out_of_the_shell() {
        std::env::set_var("NEST_TEST_SCRUBBED", "leaked");
        let ptys = Ptys::new(vec!["NEST_TEST_SCRUBBED".to_owned()]);
        let mut terminal = open_sh(&ptys, "t3");

        ptys.write("t3", b"echo \"[${NEST_TEST_SCRUBBED:-clean}]\"\n")
            .unwrap();

        terminal.wait_for("[clean]");
        assert!(!terminal.seen.contains("[leaked]"));
        ptys.kill("t3").unwrap();
    }

    #[test]
    fn characters_split_between_reads_come_out_whole() {
        let mut stream = Utf8Stream::default();
        let bytes = "é✓".as_bytes();

        let first = stream.push(&bytes[..1]);
        let second = stream.push(&bytes[1..4]);
        let third = stream.push(&bytes[4..]);

        assert_eq!(format!("{first}{second}{third}"), "é✓");
        assert_eq!(stream.push(b"a\xffb"), "a\u{fffd}b");
    }
}
