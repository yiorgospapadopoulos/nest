"""A command runner that fakes `gh` and runs everything else (git) for real."""

import json
from collections.abc import Sequence
from pathlib import Path

from harness.gitops.runner import CommandError, run_command

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


def check_run(name: str, status: str = "COMPLETED", conclusion: str = "SUCCESS") -> object:
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "detailsUrl": f"https://ci.example/{name}",
    }


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        # One-off failures keyed by the first three words of the command, such as
        # "gh pr merge", or by the first two, such as "git push".
        self.failures: dict[str, Exception] = {}
        # What `gh pr view` prints; None fails it, as if GitHub were unreachable.
        self.pr_view: str | None = None

    async def __call__(self, argv: Sequence[str], cwd: Path) -> str:
        self.calls.append(tuple(argv))
        failure = self.failures.pop(" ".join(argv[:3]), None) or self.failures.pop(
            " ".join(argv[:2]), None
        )
        if failure is not None:
            raise failure
        if tuple(argv[:3]) == ("gh", "pr", "view"):
            if self.pr_view is None:
                raise CommandError(argv, 1, "could not reach GitHub\n")
            return self.pr_view
        if tuple(argv[:3]) == ("gh", "pr", "merge"):
            return ""
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
