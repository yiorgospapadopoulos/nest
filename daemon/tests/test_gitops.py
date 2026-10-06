import asyncio
from pathlib import Path

import pytest

from harness.gitops.runner import CommandError, GitError, run_command, run_git
from tests.git_support import init_repo


async def test_run_git_returns_stdout(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")

    output = await run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)

    assert output == "main\n"


async def test_run_git_raises_with_stderr_and_exit_code(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")

    with pytest.raises(GitError) as caught:
        await run_git(["rev-parse", "--verify", "refs/heads/missing"], repo)

    assert caught.value.returncode == 128
    assert caught.value.args_ == ("rev-parse", "--verify", "refs/heads/missing")
    assert caught.value.argv == ("git", "rev-parse", "--verify", "refs/heads/missing")
    assert "fatal" in caught.value.stderr
    assert str(caught.value).startswith("git rev-parse --verify refs/heads/missing failed (128): ")


async def test_run_command_runs_any_program(tmp_path: Path) -> None:
    assert await run_command(["/bin/echo", "hi"], tmp_path) == "hi\n"


async def test_run_command_raises_a_command_error(tmp_path: Path) -> None:
    with pytest.raises(CommandError) as caught:
        await run_command(["/bin/sh", "-c", "echo nope >&2; exit 3"], tmp_path)

    assert not isinstance(caught.value, GitError)
    assert caught.value.returncode == 3
    assert caught.value.stderr == "nope\n"
    assert str(caught.value) == "/bin/sh -c echo nope >&2; exit 3 failed (3): nope"


async def test_cancelling_lets_the_git_command_finish(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    marker = tmp_path / "finished"
    slow = asyncio.ensure_future(
        run_git(["-c", f"alias.slow=!sleep 0.3 && touch {marker}", "slow"], repo)
    )
    await asyncio.sleep(0.1)

    slow.cancel()
    with pytest.raises(asyncio.CancelledError):
        await slow

    assert marker.exists()
