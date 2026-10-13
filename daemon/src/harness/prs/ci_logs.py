"""The failing checks of a pull request as a message for the agent (IMP-08).

The daemon reads each failed GitHub Actions job's log with its own `gh` login, so the agent
never needs GitHub access (D013 layer 3). Only the end of each log is kept, without color
codes or anything that looks like a credential.
"""

import re
from pathlib import Path

from harness.gitops.remotes import scrub_credentials
from harness.gitops.runner import CommandError, CommandRunner
from harness.prs.models import PrCheck

# The end of each failed job's log that goes to the agent.
TAIL_LINES = 150
MAX_LINE_CHARS = 500
INTRO = (
    "The pull request's checks failed: {names}. Here is the end of each failed job's log "
    "(the last {lines} lines), fetched by harness. Find out why they fail and fix it."
)
# A check run of GitHub Actions: https://github.com/<owner>/<repo>/actions/runs/<run>/job/<job>
_ACTIONS_JOB = re.compile(r"^https://github\.com/([^/]+/[^/]+)/actions/runs/\d+/jobs?/(\d+)")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# GitHub tokens: classic, OAuth, user-to-server, server-to-server, refresh, fine-grained.
_TOKENS = re.compile(r"\b(?:gh[opusr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")


async def feedback(run: CommandRunner, cwd: Path, failing: list[PrCheck]) -> str:
    """The message: each failing check with its log's tail, or why there is none."""
    names = ", ".join(check.name for check in failing)
    parts = [INTRO.format(names=names, lines=TAIL_LINES)]
    for check in failing:
        parts.append(f"## {check.name}\n{await _section(run, cwd, check)}")
    return "\n\n".join(parts)


async def _section(run: CommandRunner, cwd: Path, check: PrCheck) -> str:
    job = _ACTIONS_JOB.match(check.url or "")
    if job is None:
        where = f" See {check.url}" if check.url else ""
        return f"No log: this check does not run on GitHub Actions.{where}"
    repo, job_id = job.groups()
    argv = ["gh", "run", "view", "--job", job_id, "--log-failed", "--repo", repo]
    try:
        log = await run(argv, cwd)
    except CommandError as error:
        reason = _clean(error.stderr.strip().splitlines()[-1] if error.stderr.strip() else "")
        return f"harness could not read the log ({reason or 'gh failed'}). See {check.url}"
    except OSError:  # gh is not installed
        return f"harness could not read the log (gh is not available). See {check.url}"
    lines = [_clean(line)[:MAX_LINE_CHARS] for line in log.splitlines()[-TAIL_LINES:]]
    return "```\n" + "\n".join(lines) + "\n```"


def _clean(text: str) -> str:
    return _TOKENS.sub("***", scrub_credentials(_ANSI.sub("", text)))
