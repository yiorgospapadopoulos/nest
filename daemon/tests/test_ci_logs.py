from collections.abc import Sequence
from pathlib import Path

import pytest

from harness.gitops.runner import CommandError
from harness.prs.ci_logs import feedback
from harness.prs.models import PrCheck
from tests.fake_runner import actions_job


def failing(name: str, url: str | None) -> PrCheck:
    return PrCheck(name=name, state="failure", url=url)


@pytest.mark.parametrize(
    ("error", "said"),
    [
        (CommandError(["gh"], 1, ""), "could not read the log (gh failed)"),
        (CommandError(["gh"], 1, "warning\nHTTP 403: Forbidden\n"), "(HTTP 403: Forbidden)"),
        (FileNotFoundError("gh"), "could not read the log (gh is not available)"),
    ],
)
async def test_a_log_gh_cannot_read_says_why(tmp_path: Path, error: Exception, said: str) -> None:
    async def run(argv: Sequence[str], cwd: Path) -> str:
        raise error

    text = await feedback(run, tmp_path, [failing("test", actions_job(5))])

    assert said in text
    assert actions_job(5) in text


async def test_a_check_without_a_page_has_no_log(tmp_path: Path) -> None:
    async def run(argv: Sequence[str], cwd: Path) -> str:
        raise AssertionError(argv)

    text = await feedback(run, tmp_path, [failing("external", None)])

    assert text.endswith("## external\nNo log: this check does not run on GitHub Actions.")


async def test_long_lines_and_fine_grained_tokens_are_cut(tmp_path: Path) -> None:
    token = "github_pat_" + "x" * 40

    async def run(argv: Sequence[str], cwd: Path) -> str:
        return f"{'y' * 900}\nGH_TOKEN={token}\n"

    text = await feedback(run, tmp_path, [failing("test", actions_job(5))])

    assert "y" * 500 + "\n" in text
    assert "y" * 501 not in text
    assert "GH_TOKEN=***" in text
