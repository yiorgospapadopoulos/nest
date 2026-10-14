"""A command runner that fakes `gh` and runs everything else (git) for real."""

import inspect
import json
from collections.abc import Callable, Sequence
from pathlib import Path

from nestd.gitops.runner import CommandError, run_command

PR_URL = "https://github.com/me/repo/pull/7"


def pr_json(**fields: object) -> str:
    """`gh pr view --json ...` output for PR_URL: open, mergeable and without checks."""
    values: dict[str, object] = {
        "number": 7,
        "url": PR_URL,
        "title": "Do it",
        "state": "OPEN",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "reviewDecision": "",
        "headRefOid": "abc123",
        "createdAt": "2026-01-01T12:00:00Z",
        "statusCheckRollup": [],
    }
    values.update(fields)
    return json.dumps(values)


def check_run(
    name: str, status: str = "COMPLETED", conclusion: str = "SUCCESS", url: str | None = None
) -> object:
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "detailsUrl": url or f"https://ci.example/{name}",
    }


def actions_job(job_id: int) -> str:
    """A GitHub Actions job's page, as a check run's details URL."""
    return f"https://github.com/me/repo/actions/runs/99/job/{job_id}"


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        # One-off failures keyed by the first three words of the command, such as
        # "gh pr merge", or by the first two, such as "git push" (git's leading options,
        # such as `-c` overrides, left out).
        self.failures: dict[str, Exception] = {}
        # One-off canned outputs, keyed the same way, for commands that would reach out.
        self.outputs: dict[str, str] = {}
        # One-off actions run just before a command, keyed by its first two words, such as
        # a background command of the agent changing refs while the daemon publishes. An
        # action may return an awaitable, which is awaited.
        self.before: dict[str, Callable[[], object]] = {}
        # What `gh pr view` prints; None fails it, as if GitHub were unreachable.
        self.pr_view: str | None = None
        # What `gh run view --job <id> --log-failed` prints, by job id; others fail.
        self.job_logs: dict[str, str] = {}

    async def __call__(self, argv: Sequence[str], cwd: Path) -> str:
        self.calls.append(tuple(argv))
        words = _without_overrides(argv)
        action = self.before.pop(" ".join(words[:2]), None)
        result = None if action is None else action()
        if inspect.isawaitable(result):
            await result
        failure = self.failures.pop(" ".join(words[:3]), None) or self.failures.pop(
            " ".join(words[:2]), None
        )
        if failure is not None:
            raise failure
        output = self.outputs.pop(" ".join(words[:2]), None)
        if output is not None:
            return output
        if tuple(argv[:3]) == ("gh", "pr", "view"):
            if self.pr_view is None:
                raise CommandError(argv, 1, "could not reach GitHub\n")
            return self.pr_view
        if tuple(argv[:3]) == ("gh", "pr", "merge"):
            return ""
        if tuple(argv[:3]) == ("gh", "run", "view"):
            log = self.job_logs.get(argv[argv.index("--job") + 1])
            if log is None:
                raise CommandError(argv, 1, "HTTP 404: Not Found\n")
            return log
        if argv[0] == "gh":
            return f"Creating pull request for {argv[-5]}\n\n{PR_URL}\n"
        return await run_command(argv, cwd)

    def gh_calls(self, subcommand: str | None = None) -> list[tuple[str, ...]]:
        """gh calls, optionally only `gh pr <subcommand>` ones."""
        return [
            call
            for call in self.calls
            if call[0] == "gh" and (subcommand is None or call[1:3] == ("pr", subcommand))
        ]


def _without_overrides(argv: Sequence[str]) -> list[str]:
    words = list(argv)
    while len(words) > 2 and words[0] == "git" and words[1].startswith("-"):
        del words[1 : 3 if words[1] == "-c" else 2]
    return words
