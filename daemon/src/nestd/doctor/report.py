"""The bug report: a file the user reads and shares themselves. Nest sends it nowhere.

Everything passes through `redact`, which errs on removing too much. A report that loses a
log detail is fine; one that carries a token is not.
"""

import platform as python_platform
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from nestd import __version__
from nestd.doctor.checks import run_checks
from nestd.doctor.machine import Machine
from nestd.doctor.models import Check

LOG_LINES = 200
_REMOVED = "[removed]"
_PATTERNS = (
    # URL credentials, before anything else takes part of them.
    (re.compile(r"\b([a-z][a-z0-9+.-]*://)[^\s/@]+@", re.IGNORECASE), rf"\1{_REMOVED}@"),
    (re.compile(r"(?i)\bbearer\s+\S+"), f"Bearer {_REMOVED}"),
    # A whole header value, whatever its scheme.
    (re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*)[^\n]+"), rf"\1{_REMOVED}"),
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
    # Anything labelled as a secret, in logs, JSON and URLs.
    (
        re.compile(
            r"(?i)((?:[a-z0-9_-]*(?:token|secret|password|passwd|credential|cookie|api[_-]?key"
            r"|auth|key))[\"']?\s*[:=]\s*[\"']?)[^\s\"'&,;}]+"
        ),
        rf"\1{_REMOVED}",
    ),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"), _REMOVED),
    # A long unbroken run is a key or a hash until shown otherwise.
    (re.compile(r"\b[A-Za-z0-9_-]{32,}\b"), _REMOVED),
    (re.compile(r"\b[A-Za-z0-9-]+\.[A-Za-z0-9-]+\.ts\.net\b"), _REMOVED),
    # Home folders of anyone, as paths also name the user.
    (re.compile(r"/(?:Users|home)/[^/\s\"':]+"), "~"),
)


class Report(BaseModel):
    """`POST /api/setup/report`: the file, and its text to show before anything is shared."""

    path: str
    text: str


def redact(text: str, home: Path) -> str:
    cleaned = text.replace(str(home), "~")
    for pattern, replacement in _PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def _last_lines(path: Path, count: int) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-count:]
    except OSError:
        return []


def _check_line(check: Check) -> str:
    parts = [f"[{check.state}] {check.title}"]
    parts += [part for part in (check.detail, check.message) if part]
    return ": ".join(parts[:2]) + ("".join(f" ({part})" for part in parts[2:]))


def report_text(checks: Sequence[Check], log_lines: Sequence[str], when: datetime) -> str:
    return "\n".join(
        (
            f"Nest {__version__} report, {when.isoformat(timespec='seconds')}",
            f"Python {python_platform.python_version()}, {python_platform.platform()}",
            "",
            "Checks",
            *(_check_line(check) for check in checks),
            "",
            f"Last {len(log_lines)} lines of daemon.log",
            *log_lines,
            "",
        )
    )


def write_report(machine: Machine, when: datetime) -> Report:
    log = _last_lines(machine.paths.logs_dir / "daemon.log", LOG_LINES)
    text = redact(report_text(run_checks(machine), log, when), machine.home)
    folder = machine.paths.reports_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"nest-report-{when.strftime('%Y%m%d-%H%M%S')}.txt"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return Report(path=str(path), text=text)
