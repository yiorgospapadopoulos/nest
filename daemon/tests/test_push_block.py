"""A guarded run's own programs cannot push or write pull requests (D160): real git repos and
Nest's real helper scripts, with a stand-in for the user's own gh."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from nestd.providers.git_tools import DENY_REASON
from nestd.providers.push_block import (
    CODEX_HOOK,
    GH,
    NO_PUSH_ENV,
    codex_hook_hash,
    push_block,
)


def _run(
    cwd: Path, *argv: str, env: dict[str, str] | None = None, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        argv,
        cwd=cwd,
        env=None if env is None else {**os.environ, **env},
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _git(
    cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return _run(cwd, "git", *args, env=env)


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "main").stdout


@pytest.fixture
def clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A clone with a commit that is not on its bare remote yet, and that remote."""
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "Nest")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "nest@example.com")
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    assert _git(tmp_path, "init", "--bare", "-b", "main", str(remote)).returncode == 0
    assert _git(tmp_path, "init", "-b", "main", str(work)).returncode == 0
    assert _git(work, "commit", "--allow-empty", "-m", "one").returncode == 0
    assert _git(work, "remote", "add", "origin", remote.as_uri()).returncode == 0
    assert _git(work, "push", "origin", "main").returncode == 0
    assert _git(work, "commit", "--allow-empty", "-m", "two").returncode == 0
    return work, remote


async def test_a_remote_with_its_own_push_address_is_blocked(clone: tuple[Path, Path]) -> None:
    work, remote = clone
    assert _git(work, "config", "remote.origin.pushurl", str(remote)).returncode == 0
    before = _head(remote)
    block = await push_block([work])

    pushed = _git(work, "push", "origin", "main", env=dict(block.git_env))

    assert pushed.returncode != 0
    assert "nest-pushing-is-off" in pushed.stderr
    assert _head(remote) == before
    assert _git(work, "fetch", "origin", env=dict(block.git_env)).returncode == 0
    # The address git pushes to is Nest's, but the remote keeps its own.
    assert _git(work, "config", "remote.origin.pushurl").stdout.strip() == str(remote)


async def test_the_users_own_push_rewrite_does_not_beat_the_block(
    clone: tuple[Path, Path], tmp_path: Path
) -> None:
    """git picks the longest `pushInsteadOf`, and the user's own wins over Nest's empty one."""
    work, remote = clone
    fetched = tmp_path / "fetch.git"
    assert _git(tmp_path, "clone", "--bare", str(remote), str(fetched)).returncode == 0
    assert _git(work, "remote", "set-url", "origin", str(fetched)).returncode == 0
    assert _git(work, "config", f"url.{remote}.pushInsteadOf", str(fetched)).returncode == 0
    before = _head(remote)
    block = await push_block([work])

    pushed = _git(work, "push", "origin", "main", env=dict(block.git_env))

    assert pushed.returncode != 0
    assert _head(remote) == before
    assert (
        _git(work, "pull", "--no-edit", "origin", "main", env=dict(block.git_env)).returncode == 0
    )


async def test_plain_remotes_need_only_the_block_for_every_url(
    clone: tuple[Path, Path], tmp_path: Path
) -> None:
    """Naming a remote would make a repository without it show one (`git fetch --all`)."""
    work, _ = clone
    plain = tmp_path / "plain"
    assert _git(tmp_path, "init", "-b", "main", str(plain)).returncode == 0

    block = await push_block([work, plain, tmp_path / "missing"])

    assert dict(block.git_env) == NO_PUSH_ENV
    assert _git(plain, "remote", env=dict(block.git_env)).stdout == ""


async def test_a_script_cannot_open_a_pull_request_through_gh(tmp_path: Path) -> None:
    """Nest's gh comes first on PATH and refuses before the user's own gh runs."""
    users = tmp_path / "users-bin"
    users.mkdir()
    ran = tmp_path / "ran"
    stand_in = users / GH
    stand_in.write_text(f'#!/bin/sh\necho "$@" >> {ran}\necho users-gh\n', encoding="utf-8")
    stand_in.chmod(0o755)
    script = tmp_path / "release.sh"
    script.write_text("#!/bin/sh\ngh pr create --fill\n", encoding="utf-8")
    script.chmod(0o755)
    block = await push_block([tmp_path])
    env = block.env(f"{users}{os.pathsep}/usr/bin{os.pathsep}/bin")

    refused = _run(tmp_path, str(script), env=env)

    assert refused.returncode != 0
    assert DENY_REASON in refused.stderr
    assert not ran.exists()


@pytest.mark.parametrize(
    ("args", "allowed"),
    [
        (("pr", "view", "12", "--json", "state"), True),
        (("api", "repos/o/r/pulls"), True),
        (("--version",), True),
        (("pr", "merge", "12", "--squash"), False),
        (("api", "-X", "POST", "repos/o/r/pulls"), False),
        (("auth", "token"), False),
        # An alias or an extension: what it runs cannot be read.
        (("prc",), False),
    ],
)
async def test_nests_gh_runs_the_users_gh_only_for_reads(
    tmp_path: Path, args: tuple[str, ...], allowed: bool
) -> None:
    users = tmp_path / "users-bin"
    users.mkdir()
    stand_in = users / GH
    stand_in.write_text('#!/bin/sh\necho "users-gh $*"\n', encoding="utf-8")
    stand_in.chmod(0o755)
    block = await push_block([tmp_path])

    result = _run(tmp_path, GH, *args, env=block.env(f"{users}{os.pathsep}/usr/bin"))

    assert (result.returncode == 0) is allowed
    assert ("users-gh" in result.stdout) is allowed
    if allowed:
        assert result.stdout.strip() == f"users-gh {' '.join(args)}"


def _hook_event(command: str, **fields: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": "/work",
            **fields,
        }
    )


@pytest.mark.parametrize(
    ("command", "fields", "denied"),
    [
        ("git push origin main", {"agent_id": "019a"}, True),
        ("gh pr create --fill", {"agent_id": "019a", "agent_type": "worker"}, True),
        ("git status", {"agent_id": "019a"}, False),
        # The chat itself may push when asked (B127).
        ("git push origin main", {}, False),
    ],
)
async def test_codexs_hook_refuses_only_a_subagents_push(
    tmp_path: Path, command: str, fields: dict[str, str], denied: bool
) -> None:
    block = await push_block([tmp_path])

    result = _run(tmp_path, str(block.bin_dir / CODEX_HOOK), stdin=_hook_event(command, **fields))

    assert result.returncode == 0
    if denied:
        answer = json.loads(result.stdout)["hookSpecificOutput"]
        assert answer["permissionDecision"] == "deny"
        assert answer["permissionDecisionReason"] == DENY_REASON
    else:
        assert result.stdout == ""


def test_codex_trusts_the_hook_by_the_hash_nest_gives() -> None:
    """The hash Codex 0.163.0's `hooks/list` reported as trusted for this exact hook."""
    assert codex_hook_hash("/opt/nest/codex-subagent-hook", 60) == (
        "sha256:c7a18b54b8e64c6766a931a23b8b2caed84b1574e1d59ca0324a037a5aa44125"
    )


async def test_the_helpers_come_back_when_something_removes_them(tmp_path: Path) -> None:
    block = await push_block([tmp_path])
    (block.bin_dir / GH).unlink()

    again = await push_block([tmp_path])

    assert os.access(again.bin_dir / GH, os.X_OK)
    assert again.env("/usr/bin")["PATH"] == f"{again.bin_dir}{os.pathsep}/usr/bin"
