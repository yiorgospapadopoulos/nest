"""The bug report: a file the user reads and shares themselves. Nest sends it nowhere.

Everything passes through `redact`, which errs on removing too much. A report that loses a
log detail is fine; one that carries a token is not.
"""

import platform as python_platform
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from pydantic import BaseModel

from nestd import __version__
from nestd.auth.devices import CODE_ALPHABET, CODE_LENGTH
from nestd.doctor.checks import by_rank, run_checks
from nestd.doctor.machine import Machine, system_line
from nestd.doctor.models import Check
from nestd.logging_setup import ENGINE_STDERR_LOGGER
from nestd.release import ISSUES_URL

LOG_LINES = 200
_REMOVED = "[removed]"
_LABEL = (
    r"[a-z0-9_-]*(?:token|secret|password|passwd|passphrase|credential|cookie|api[_-]?key"
    r"|auth|key)[a-z0-9_-]*"
)
_PATTERNS = (
    # URL credentials up to the last `@`, before anything else takes part of them.
    (re.compile(r"\b([a-z][a-z0-9+.-]*://)\S*@", re.IGNORECASE), rf"\1{_REMOVED}@"),
    # An SSH remote's owner and repository, before the email rule takes its host (B159 R50).
    (re.compile(r"\b[\w.-]+@([\w-]+(?:\.[\w-]+)+):[^\s\"']+"), rf"\1/{_REMOVED}"),
    # A pairing code, labelled or in a line about pairing (B159 R50). Only Nest's own
    # alphabet and length, so error codes such as `code: 'ENOENT'` stay.
    (
        re.compile(rf"(\b(?i:code)[\\\"']*\s*[:=]\s*[\\\"']*)[{CODE_ALPHABET}]{{{CODE_LENGTH}}}\b"),
        rf"\1{_REMOVED}",
    ),
    (re.compile(r"(?i)\bbearer\s+\S+"), f"Bearer {_REMOVED}"),
    # A whole header value, whatever its scheme.
    (
        re.compile(r"(?i)((?:authorization|set-cookie|cookie)[\\\"']*\s*[:=]\s*)[^\n]+"),
        rf"\1{_REMOVED}",
    ),
    # Known token shapes: GitHub, Anthropic and OpenAI, Slack, Google, ntfy, JWTs.
    (
        re.compile(
            r"\b(?:gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}"
            r"|sk-[A-Za-z0-9_-]{8,}|xox[a-z]-[A-Za-z0-9-]{8,}|AIza[A-Za-z0-9_-]{16,}"
            r"|tk_[a-z0-9]{8,})"
        ),
        _REMOVED,
    ),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), _REMOVED),
    # A command line's `--token value`.
    (re.compile(rf"(?i)(--{_LABEL}[= ])\S+"), rf"\1{_REMOVED}"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"), _REMOVED),
    (re.compile(r"\b[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.ts\.net\b"), _REMOVED),
    # Home folders of anyone, as paths also name the user.
    (re.compile(r"/(?:Users|home)/[^/\s\"':]+"), "~"),
)

_URL = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]*://(?:[^\s/@]*@)?([^\s/:@\"'<>]+)(?::\d+)?)/[^\s\"'<>]*"
)
_LOCAL_HOSTS = frozenset(("127.0.0.1", "localhost", "[::1]"))
_PAIRING_LINE = re.compile(r"(?i)\bpair")
_PAIRING_CODE = re.compile(rf"\b[{CODE_ALPHABET}]{{{CODE_LENGTH}}}\b")
# A path under the home folder; inner parts may hold spaces, as `Application Support` does.
_PART = r"[^/\s\"'`:,;()<>]+"
_HOME_PATH = re.compile(rf"~((?:/{_PART}(?: {_PART})*(?=/))*(?:/{_PART})?)")
# Where Nest and the engines keep their own files; any other home path names a project.
_KEPT_ROOTS = frozenset(
    ("Library", ".config", ".local", ".cache", ".claude", ".codex", ".gemini", ".npm", ".nvm")
)
# Inside those, what follows these parts names a project or a file of the user's.
_HIDE_AFTER = frozenset(("worktrees", "projects", "repos", "Mobile Documents", "CloudStorage"))
_PATH = "[path]"
# An exception's message, after its type, and the quoted text in it.
_EXCEPTION = re.compile(r"\b([A-Za-z_][\w.]*(?:Error|Exception)): (.*)$")
_EXCEPTION_KEPT = 40
# A failed command's exit status, which a cut message keeps.
_EXIT_STATUS = re.compile(r"exit status -?\d+\.?$")
_QUOTED = re.compile(r"\"[^\"\n]{12,}\"|'[^'\n]{12,}'")
# A long quoted value of a key anywhere, such as a prompt in a JSON body.
_LONG_VALUE = re.compile(r"(?i)([\"'][\w-]+[\\\"']*\s*:\s*)(\\?[\"'])[^\"'\n]{24,}[\"']")


# Anything labelled as a secret, in logs, JSON (escaped too) and URLs, quoted values whole.
_LABELLED = (
    re.compile(
        rf"(?i)(?<!\w)({_LABEL}[\\\"']*\s*[:=]\s*)"
        r"(?:\\?\"[^\"\n]*\"|'[^'\n]*'|[\\\"']*[^\s\"'&,;}\\]+)"
    ),
    rf"\1{_REMOVED}",
)


class Report(BaseModel):
    """`POST /api/setup/report`: the file, and its text to show before anything is shared."""

    path: str
    text: str
    # A new GitHub issue that asks for the report, never with it in the address.
    issue_url: str
    # Whether the issue asks for the file, which the apps then show in its folder. Always
    # true now; kept so apps that read it go on showing the file.
    attach_file: bool


def issue_url(file_name: str) -> str:
    """Never with the report in it: the address reaches github.com before the user
    submits (B159 R50). They attach the file or paste what they copied."""
    title = f"Nest {__version__}: "
    body = f"What happened:\n\n\nAttach or paste the bug report: {file_name}\n"
    return f"{ISSUES_URL}?{urlencode({'title': title, 'body': body})}"


# A long unbroken run is a key, a hash or base64 until shown otherwise. A path is shown
# otherwise: short parts between slashes, mostly plain lowercase words, never `+` or `=`.
_LONG_RUN = re.compile(r"[A-Za-z0-9+/=_-]{32,}")
_PATH_PART_LIMIT = 24
_WORD = re.compile(r"[a-z][a-z0-9_-]*[a-z]")
# A log line's own start: time, level and the logger's dotted name, such as
# `nestd.auth.token_socket:`, which would otherwise read as a label for what follows.
_LOG_PREFIX = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} (?:DEBUG|INFO|WARNING|ERROR|CRITICAL) "
    r"[A-Za-z_][\w.]*: )(.*)$"
)
# The routine answers of the daemon's own server, which say nothing about a problem.
_ROUTINE = re.compile(r'uvicorn\.access: .*" [123]\d\d$')
# A log line's start, with the logger's name.
_LOG_START = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} [A-Z]+ ([\w.]+): ")
# How far back to look for the lines that are kept.
_LOG_SCAN = 5000


def _long_run(match: re.Match[str]) -> str:
    run = match.group(0)
    parts = [part for part in run.split("/") if part]
    words = [part for part in parts if _WORD.fullmatch(part) and len(part) >= 3]
    path_like = (
        len(parts) > 1
        and "+" not in run
        and "=" not in run
        and all(len(part) < _PATH_PART_LIMIT for part in parts)
        and len(words) * 2 >= len(parts)
    )
    return run if path_like else _REMOVED


def _url(match: re.Match[str]) -> str:
    """A web address keeps its host only, as a repository's path names its owner."""
    if match.group(2).lower() in _LOCAL_HOSTS:
        return match.group(0)
    return f"{match.group(1)}/{_REMOVED}"


def _home_path(match: re.Match[str]) -> str:
    parts = [part for part in match.group(1).split("/") if part]
    if not parts:
        return match.group(0)
    if parts[0] not in _KEPT_ROOTS:
        return f"~/{_PATH}"
    for index, part in enumerate(parts[:-1]):
        if part in _HIDE_AFTER:
            parts[index + 1 :] = [_PATH]
            break
    return "~/" + "/".join(parts)


def _exception(match: re.Match[str]) -> str:
    """An exception's type and a short part of its message, without quoted text."""
    message = _QUOTED.sub(_REMOVED, match.group(2))
    if len(message) > _EXCEPTION_KEPT:
        status = _EXIT_STATUS.search(message)
        if status is None:
            message = message[:_EXCEPTION_KEPT] + " [cut]"
        else:
            kept = message[: min(_EXCEPTION_KEPT, status.start())].rstrip()
            message = f"{kept} [cut] {status.group(0)}"
    return f"{match.group(1)}: {message}"


def _clean(text: str, *, labels: bool = True) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    if _PAIRING_LINE.search(text):
        text = _PAIRING_CODE.sub(_REMOVED, text)
    text = _URL.sub(_url, text)
    text = _HOME_PATH.sub(_home_path, text)
    if labels:
        text = _LABELLED[0].sub(_LABELLED[1], text)
        text = _LONG_VALUE.sub(rf"\1\2{_REMOVED}\2", text)
        text = _EXCEPTION.sub(_exception, text)
    return _LONG_RUN.sub(_long_run, text)


def _clean_line(line: str) -> str:
    """A log line's start gets every rule but the labelled one, which would take the
    logger's name, such as `nestd.auth.token_socket:`, for a label."""
    prefix = _LOG_PREFIX.match(line)
    if prefix is None:
        return _clean(line)
    return _clean(prefix.group(1), labels=False) + _clean(prefix.group(2))


def redact(text: str, home: Path) -> str:
    """Line by line, so a log line's own start is never read as a label."""
    cleaned = text.replace(str(home), "~")
    return "\n".join(_clean_line(line) for line in cleaned.split("\n"))


def _last_lines(path: Path, count: int) -> list[str]:
    """The last lines that could say something, without the server's routine answers or
    what the engines wrote to stderr, which can quote the user's work (B159 R50)."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-_LOG_SCAN:]
    except OSError:
        return []
    kept: list[str] = []
    engine = False
    for line in lines:
        start = _LOG_START.match(line)
        if start is not None:
            engine = start.group(1) == ENGINE_STDERR_LOGGER
        if not engine and not _ROUTINE.search(line):
            kept.append(line)
    return kept[-count:]


def _check_line(check: Check) -> str:
    parts = [f"[{check.state}] {check.title}"]
    parts += [part for part in (check.detail, check.message) if part]
    return ": ".join(parts[:2]) + ("".join(f" ({part})" for part in parts[2:]))


def report_text(checks: Sequence[Check], log_lines: Sequence[str], when: datetime) -> str:
    return "\n".join(
        (
            f"Nest {__version__} report, {when.isoformat(timespec='seconds')}",
            f"Python {python_platform.python_version()}, {system_line()}",
            "",
            "Checks",
            *(_check_line(check) for check in checks),
            "",
            f"Last {len(log_lines)} lines of daemon.log",
            *log_lines,
            "",
        )
    )


def write_report(machine: Machine, when: datetime, app_checks: Sequence[Check] = ()) -> Report:
    """`app_checks` are the app's own answers, for what only it can check."""
    log = _last_lines(machine.paths.logs_dir / "daemon.log", LOG_LINES)
    answers = {check.id: check for check in app_checks}
    checks = by_rank([answers.get(check.id, check) for check in run_checks(machine)])
    text = redact(report_text(checks, log, when), machine.home)
    folder = machine.paths.reports_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"nest-report-{when.strftime('%Y%m%d-%H%M%S')}.txt"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return Report(path=str(path), text=text, issue_url=issue_url(path.name), attach_file=True)
