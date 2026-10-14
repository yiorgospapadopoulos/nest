from collections.abc import Sequence
from pathlib import Path

import pytest

from harness.gitops.remotes import github_repo, push_urls, scrub_credentials, scrub_url
from harness.gitops.runner import run_command
from harness.gitops.safety import (
    HARDENED,
    RepoSetting,
    filter_overrides,
    repo_settings,
    unsafe_settings,
)
from tests.git_support import git, init_repo


def local(key: str, value: str = "x") -> RepoSetting:
    return RepoSetting("local", key, value)


def test_repo_settings_keep_only_the_repositorys_own_scopes() -> None:
    listing = (
        "system\0credential.helper\nosxkeychain\0"
        "global\0user.name\nMe\0"
        "local\0core.bare\nfalse\0"
        "local\0section.flag\0"
        "worktree\0core.sshcommand\nssh -v\nmore\0"
        "command\0core.hookspath\n/dev/null\0"
    )

    assert repo_settings(listing) == [
        RepoSetting("local", "core.bare", "false"),
        RepoSetting("local", "section.flag", ""),
        RepoSetting("worktree", "core.sshcommand", "ssh -v\nmore"),
    ]


@pytest.mark.parametrize(
    "setting",
    [
        local("core.bare", "false"),
        local("remote.origin.url", "https://example.com/r.git"),
        local("http.postbuffer", "524288000"),
        local("http.https://example.com.lowspeedtime", "60"),
        local("protocol.version", "2"),
        local("core.fsmonitor", "true"),
        local("core.fsmonitor", "FALSE"),
        local("filter.anything.required", "true"),
        local("filter.lfs.clean", "git-lfs clean -- %f"),
        local("filter.lfs.process", "git-lfs filter-process"),
        local("core.hookspath", "/anywhere"),
    ],
)
def test_ordinary_settings_are_safe(setting: RepoSetting) -> None:
    assert unsafe_settings([setting]) == []


def test_unsafe_settings_are_named_once_with_their_reason() -> None:
    settings = [
        local("filter.lfs.clean", "evil"),
        local("http.https://example.com.proxy", "http://evil"),
        local("Credential.Helper", "evil"),
        local("Credential.Helper", "evil"),
    ]

    assert unsafe_settings(settings) == [
        "filter.lfs.clean (runs a program on your files)",
        "http.https://example.com.proxy (changes where or how data is sent)",
        "Credential.Helper (handles your credentials)",
    ]


def test_filter_overrides_switch_off_each_driver_once() -> None:
    settings = [
        local("filter.Mine.Two.clean"),
        local("filter.Mine.Two.smudge"),
        local("filter.lfs.process"),
        local("filter.loose"),
        local("core.bare", "false"),
    ]

    assert filter_overrides(settings) == [
        *("-c", "filter.Mine.Two.clean=", "-c", "filter.Mine.Two.smudge="),
        *("-c", "filter.Mine.Two.process=", "-c", "filter.Mine.Two.required=false"),
        *("-c", "filter.lfs.clean=", "-c", "filter.lfs.smudge="),
        *("-c", "filter.lfs.process=", "-c", "filter.lfs.required=false"),
    ]
    assert filter_overrides([]) == []


def test_checkout_overrides_keep_git_lfs_as_it_installs_itself() -> None:
    """Checking out a worktree must still run git-lfs, but not a driver the agent added."""
    lfs = [
        local("filter.lfs.clean", "git-lfs clean -- %f"),
        local("filter.lfs.smudge", "git-lfs smudge -- %f"),
        local("filter.lfs.process", "git-lfs filter-process"),
        local("filter.lfs.required", "true"),
    ]

    assert filter_overrides(lfs, only_unsafe=True) == []
    assert filter_overrides([local("filter.only.required", "true")], only_unsafe=True) == []
    assert filter_overrides(
        [*lfs[:2], local("filter.lfs.process", "sh -c evil"), local("filter.x.clean")],
        only_unsafe=True,
    ) == [
        *("-c", "filter.lfs.clean=", "-c", "filter.lfs.smudge="),
        *("-c", "filter.lfs.process=", "-c", "filter.lfs.required=false"),
        *("-c", "filter.x.clean=", "-c", "filter.x.smudge="),
        *("-c", "filter.x.process=", "-c", "filter.x.required=false"),
    ]


def test_a_filter_driver_named_with_an_equals_sign_cannot_be_switched_off() -> None:
    with pytest.raises(ValueError, match="'a=b' cannot be switched off"):
        filter_overrides([local("filter.a=b.clean")])


@pytest.mark.parametrize(
    ("url", "scrubbed"),
    [
        ("https://me:token@github.com/me/repo.git", "https://github.com/me/repo.git"),
        ("HTTP://token@example.com:8080/r", "http://example.com:8080/r"),
        ("https://github.com/me/repo.git", "https://github.com/me/repo.git"),
        ("ssh://git@github.com/me/repo.git", "ssh://git@github.com/me/repo.git"),
        ("git@github.com:me/repo.git", "git@github.com:me/repo.git"),
        ("/srv/git/repo.git", "/srv/git/repo.git"),
    ],
)
def test_scrub_url_leaves_out_http_credentials(url: str, scrubbed: str) -> None:
    assert scrub_url(url) == scrubbed


@pytest.mark.parametrize(
    ("text", "scrubbed"),
    [
        (
            "fatal: unable to access 'https://me:ghp_secret@github.com/me/repo.git/': 403",
            "fatal: unable to access 'https://github.com/me/repo.git/': 403",
        ),
        (
            "remote: see HTTPS://x-access-token:abc@Example.com/a and http://tok@b.example/c",
            "remote: see HTTPS://Example.com/a and http://b.example/c",
        ),
        (
            "fatal: could not read from ssh://git@github.com/me/repo.git or git@github.com:me/r",
            "fatal: could not read from ssh://git@github.com/me/repo.git or git@github.com:me/r",
        ),
        ("error: failed to push some refs", "error: failed to push some refs"),
    ],
)
def test_scrub_credentials_leaves_out_http_credentials_in_text(text: str, scrubbed: str) -> None:
    """H-06: git's error output can quote a remote URL with its user name and token."""
    assert scrub_credentials(text) == scrubbed


@pytest.mark.parametrize(
    ("url", "repo"),
    [
        ("git@github.com:me/repo.git", "me/repo"),
        ("git@GitHub.com:me/repo", "me/repo"),
        ("github.com:me/repo.git", "me/repo"),
        ("https://github.com/me/repo.git", "me/repo"),
        ("https://github.com/me/repo/", "me/repo"),
        ("ssh://git@github.com/me/repo.git", "me/repo"),
        ("https://gitlab.com/me/repo.git", None),
        ("git@github.com-work:me/repo.git", None),
        ("https://github.com/me", None),
        ("https://github.com/me/repo/extra", None),
        ("git@github.com:/abs/repo.git", None),
        ("/srv/git/repo.git", None),
        ("https://github.com//repo", None),
    ],
)
def test_github_repo_names_github_com_repositories_only(url: str, repo: str | None) -> None:
    assert github_repo(url) == repo


async def test_push_urls_are_empty_without_an_origin(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")

    assert await push_urls(repo, run_command) == []


@pytest.mark.parametrize(
    "setting",
    [
        local("diff.external", "/opt/evil"),
        local("diff.secret.command", "/opt/evil"),
        local("diff.secret.textconv", "/opt/evil"),
        local("merge.secret.driver", "/opt/evil %O %A %B"),
        local("core.editor", "/opt/evil"),
        local("sequence.editor", "/opt/evil"),
        local("core.pager", "/opt/evil"),
        local("pager.log", "/opt/evil"),
        local("interactive.difffilter", "/opt/evil"),
    ],
)
def test_settings_that_run_diff_merge_editor_or_pager_programs_are_unsafe(
    setting: RepoSetting,
) -> None:
    """A security review flagged programs git can run from these keys during diffs and commits."""
    assert unsafe_settings([setting]) == [f"{setting.key} (runs a program)"]


async def test_push_urls_are_read_with_hardened_git(tmp_path: Path) -> None:
    """SEC-17: every git command the daemon runs in a repository the agent can write."""
    repo = init_repo(tmp_path / "repo")
    git(repo, "remote", "add", "origin", "https://me:token@github.com/me/repo.git")
    calls: list[Sequence[str]] = []

    async def recording(argv: Sequence[str], cwd: Path) -> str:
        calls.append(argv)
        return await run_command(argv, cwd)

    assert await push_urls(repo, recording) == ["https://github.com/me/repo.git"]
    ((program, *rest),) = calls
    assert (program, tuple(rest[: len(HARDENED)])) == ("git", HARDENED)
