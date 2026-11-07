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
from nestd.doctor.checks import by_rank, run_checks
from nestd.doctor.machine import Machine, system_line
from nestd.doctor.models import Check
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
    # Anything labelled as a secret, in logs, JSON (escaped too) and URLs, quoted values whole.
    (
        re.compile(
            rf"(?i)(?<!\w)({_LABEL}[\\\"']*\s*[:=]\s*)"
            r"(?:\\?\"[^\"\n]*\"|'[^'\n]*'|[\\\"']*[^\s\"'&,;}\\]+)"
        ),
        rf"\1{_REMOVED}",
    ),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"), _REMOVED),
    (re.compile(r"\b[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.ts\.net\b"), _REMOVED),
    # Home folders of anyone, as paths also name the user.
    (re.compile(r"/(?:Users|home)/[^/\s\"':]+"), "~"),
)


class Report(BaseModel):
    """`POST /api/setup/report`: the file, and its text to show before anything is shared."""

    path: str
    text: str
    # A new GitHub issue with the report filled in, for the user to read and submit; when
    # the report is too long for an address, one that asks them to attach the file.
    issue_url: str
    # Whether the issue asks for the file, which the apps then show in its folder.
    attach_file: bool


def issue_url(text: str, file_name: str) -> str:
    title = f"Nest {__version__}: "
    body = f"What happened:\n\n\n```\n{text}\n```\n"
    url = f"{ISSUES_URL}?{urlencode({'title': title, 'body': body})}"
    if len(url) <= _ISSUE_URL_LIMIT:
        return url
    short = f"What happened:\n\n\nThe report is attached: {file_name}\n"
    return f"{ISSUES_URL}?{urlencode({'title': title, 'body': short})}"


# A long unbroken run is a key, a hash or base64 until shown otherwise. A path is shown
# otherwise: short parts between slashes, mostly plain lowercase words, never `+` or `=`.
_LONG_RUN = re.compile(r"[A-Za-z0-9+/=_-]{32,}")
_PATH_PART_LIMIT = 24
_WORD = re.compile(r"[a-z][a-z0-9_-]*[a-z]")
# A log line's own start: time, level and the logger's dotted name, such as
# `nestd.auth.token_socket:`, which would otherwise read as a label for what follows.
_LOG_PREFIX = re.compile(r"^(\S+ \S+ [A-Z]+ [\w.]+: )(.*)$")
# The routine answers of the daemon's own server, which say nothing about a problem.
_ROUTINE = re.compile(r'uvicorn\.access: .*" [123]\d\d$')
# How far back to look for the lines that are kept.
_LOG_SCAN = 5000
_ISSUE_URL_LIMIT = 7000


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


def _clean(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return _LONG_RUN.sub(_long_run, text)


def _clean_line(line: str) -> str:
    prefix = _LOG_PREFIX.match(line)
    if prefix is None:
        return _clean(line)
    return prefix.group(1) + _clean(prefix.group(2))


def redact(text: str, home: Path) -> str:
    """Line by line, so a log line's own start is never read as a label."""
    cleaned = text.replace(str(home), "~")
    return "\n".join(_clean_line(line) for line in cleaned.split("\n"))


def _last_lines(path: Path, count: int) -> list[str]:
    """The last lines that could say something, without the server's routine answers."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-_LOG_SCAN:]
    except OSError:
        return []
    return [line for line in lines if not _ROUTINE.search(line)][-count:]


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
    url = issue_url(text, path.name)
    return Report(path=str(path), text=text, issue_url=url, attach_file=path.name in url)
