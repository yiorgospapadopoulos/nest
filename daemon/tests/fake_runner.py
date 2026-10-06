"""A command runner that fakes `gh` and runs everything else (git) for real."""

from collections.abc import Sequence
from pathlib import Path

from harness.gitops.runner import run_command

PR_URL = "https://github.com/me/repo/pull/7"


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        # One-off failures keyed by the first two words of the command, e.g. "git push".
        self.failures: dict[str, Exception] = {}

    async def __call__(self, argv: Sequence[str], cwd: Path) -> str:
        self.calls.append(tuple(argv))
        failure = self.failures.pop(" ".join(argv[:2]), None)
        if failure is not None:
            raise failure
        if argv[0] == "gh":
            return f"Creating pull request for {argv[-5]}\n\n{PR_URL}\n"
        return await run_command(argv, cwd)

    def gh_calls(self) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[0] == "gh"]
