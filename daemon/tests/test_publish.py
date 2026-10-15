from collections.abc import Sequence
from pathlib import Path

import pytest

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.runner import CommandError
from nestd.gitops.safety import HARDENED
from nestd.review.errors import (
    GitActionError,
    HeadChangedError,
    NestedRepositoryError,
    NothingToCommitError,
    RemoteChangedError,
    RemoteNotConfirmedError,
    UnsafeBranchError,
    UnsafeRepoConfigError,
)
from nestd.review.publish import GitPublisher, PublishPlan, PullRequest
from nestd.sessions.models import Session
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.fake_runner import PR_URL, FakeRunner
from tests.fakes import FakeClock
from tests.git_support import commit_file, git, init_repo, with_origin
from tests.nested_support import add_nested_repo, plant_filter
from tests.test_session_store import new_session

PR = PullRequest(
    base="main", title="Fix the bug", body="Fix the bug\n\nDone.", summary="Done.\n1 file changed"
)


class Env:
    def __init__(self, tmp_path: Path, db: Database, clock: FakeClock) -> None:
        self.repo = init_repo(tmp_path / "repo")
        self.origin = with_origin(self.repo, tmp_path / "origin.git")
        self.worktree = tmp_path / "wt"
        self.base = git(self.repo, "rev-parse", "HEAD").strip()
        self.bus = EventBus(db, clock)
        self.store = SessionStore(db, clock)
        self.runner = FakeRunner()
        # Where gh runs when it is told the repository (SEC-17).
        self.neutral = tmp_path / "data"
        self.neutral.mkdir()
        self.publisher = GitPublisher(self.runner, self.store, self.bus, self.neutral)

    async def worktree_session(self) -> Session:
        git(self.repo, "worktree", "add", "-q", "-b", "agent/fix", str(self.worktree), self.base)
        session = await self.store.create(new_session(base_ref=self.base))
        return await self.store.update(
            session.id, cwd=self.worktree, worktree_path=self.worktree, branch="agent/fix"
        )

    async def in_place_session(self) -> Session:
        return await self.store.create(
            new_session(mode="in_place", cwd=self.repo, base_ref=self.base)
        )

    def plan(self, **fields: object) -> PublishPlan:
        """A plan whose checked HEAD is the checkout's HEAD now, as approve's checks see it."""
        checkout = self.worktree if self.worktree.exists() else self.repo
        head = git(checkout, "rev-parse", "HEAD").strip()
        return plan(**{"remote_url": str(self.origin), "head": head, **fields})

    async def events(self, session_id: str) -> list[tuple[str, object]]:
        return [(e.type, e.payload) for e in await self.bus.session_events(session_id)]


@pytest.fixture
def env(tmp_path: Path, db: Database, clock: FakeClock) -> Env:
    return Env(tmp_path, db, clock)


def plan(**fields: object) -> PublishPlan:
    values: dict[str, object] = {
        "message": "Fix the bug",
        "head": None,
        "paths": None,
        "push": True,
        "pull_request": PR,
    }
    values.update(fields)
    return PublishPlan(**values)  # pyright: ignore[reportArgumentType]


async def test_a_worktree_is_committed_pushed_and_opened_as_a_pull_request(env: Env) -> None:
    session = await env.worktree_session()
    (env.worktree / "README.md").write_text("better\n", encoding="utf-8")
    (env.worktree / "new.txt").write_text("new\n", encoding="utf-8")

    published = await env.publisher.publish(session, env.plan())

    sha = git(env.worktree, "rev-parse", "HEAD").strip()
    assert published.commit_sha == sha
    assert published.pr_url == PR_URL
    assert published.pr_summary == "Done.\n1 file changed"
    assert git(env.worktree, "log", "-1", "--format=%s%n%an").split("\n")[:2] == [
        "Fix the bug",
        "Test",
    ]
    assert git(env.worktree, "status", "--porcelain") == ""
    assert git(env.origin, "rev-parse", "agent/fix").strip() == sha
    assert git(env.worktree, "rev-parse", "--abbrev-ref", "agent/fix@{upstream}").strip() == (
        "origin/agent/fix"
    )
    assert push_calls(env.runner)[0][-1] == f"{sha}:refs/heads/agent/fix"
    assert env.runner.gh_calls() == [
        (
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            "agent/fix",
            "--title",
            "Fix the bug",
            "--body",
            "Fix the bug\n\nDone.",
        )
    ]
    assert await env.events(session.id) == [
        (types.GIT_COMMITTED, {"sha": sha}),
        (types.GIT_PUSHED, {"remote": "origin", "branch": "agent/fix"}),
        (types.PR_OPENED, {"url": PR_URL}),
    ]


async def test_a_failed_step_is_reported_and_a_retry_skips_what_is_done(env: Env) -> None:
    session = await env.worktree_session()
    (env.worktree / "README.md").write_text("better\n", encoding="utf-8")
    env.runner.failures["git push"] = CommandError(["git", "push"], 128, "remote hung up\n")

    with pytest.raises(GitActionError) as caught:
        await env.publisher.publish(session, env.plan())
    failed = await env.store.get(session.id)
    retried = await env.publisher.publish(failed, env.plan())
    again = await env.publisher.publish(retried, env.plan())

    assert caught.value.status_code == 502
    assert caught.value.payload() == {
        "detail": "git push failed: remote hung up",
        "step": "push",
        "stderr": "remote hung up\n",
    }
    assert failed.commit_sha is not None
    assert failed.pr_url is None
    assert git(env.worktree, "rev-list", "--count", f"{env.base}..HEAD").strip() == "1"
    assert retried.commit_sha == failed.commit_sha
    assert retried.pr_url == again.pr_url == PR_URL
    assert len(env.runner.gh_calls()) == 1
    assert (types.GIT_FAILED, {"step": "push", "stderr": "remote hung up\n"}) in await env.events(
        session.id
    )


async def test_credentials_in_git_output_never_reach_clients(env: Env) -> None:
    """H-06: the failure is published and returned without the URL's user name and token."""
    session = await env.worktree_session()
    (env.worktree / "README.md").write_text("better\n", encoding="utf-8")
    stderr = "fatal: unable to access 'https://me:ghp_secret@github.com/me/repo.git/': 403\n"
    env.runner.failures["git push"] = CommandError(["git", "push"], 128, stderr)

    with pytest.raises(GitActionError) as caught:
        await env.publisher.publish(session, env.plan())

    scrubbed = "fatal: unable to access 'https://github.com/me/repo.git/': 403\n"
    assert caught.value.payload() == {
        "detail": f"git push failed: {scrubbed.strip()}",
        "step": "push",
        "stderr": scrubbed,
    }
    assert (types.GIT_FAILED, {"step": "push", "stderr": scrubbed}) in await env.events(session.id)


async def test_in_place_commits_only_the_chosen_files(env: Env) -> None:
    commit_file(env.repo, "old.txt", "old\n")
    commit_file(env.repo, "doomed.txt", "bye\n")
    git(env.repo, "push", "-q", "origin", "main")
    env.base = git(env.repo, "rev-parse", "HEAD").strip()
    session = await env.in_place_session()
    (env.repo / "agent.txt").write_text("from the agent\n", encoding="utf-8")
    (env.repo / "doomed.txt").unlink()
    git(env.repo, "mv", "old.txt", "renamed.txt")
    (env.repo / "mine.txt").write_text("the user's own work\n", encoding="utf-8")
    (env.repo / "staged.txt").write_text("staged by the user\n", encoding="utf-8")
    git(env.repo, "add", "staged.txt")

    published = await env.publisher.publish(
        session,
        env.plan(
            paths=["agent.txt", "doomed.txt", "old.txt", "renamed.txt"],
            pull_request=None,
        ),
    )

    committed = git(env.repo, "show", "--name-status", "--format=", "HEAD").split("\n")
    assert sorted(line for line in committed if line) == [
        "A\tagent.txt",
        "D\tdoomed.txt",
        "R100\told.txt\trenamed.txt",
    ]
    assert git(env.repo, "status", "--porcelain").splitlines() == ["A  staged.txt", "?? mine.txt"]
    assert git(env.origin, "rev-parse", "main").strip() == published.commit_sha
    assert env.runner.gh_calls() == []


async def test_in_place_with_only_staged_removals(env: Env) -> None:
    commit_file(env.repo, "old.txt", "old\n")
    env.base = git(env.repo, "rev-parse", "HEAD").strip()
    session = await env.in_place_session()
    git(env.repo, "rm", "-q", "old.txt")

    published = await env.publisher.publish(session, env.plan(paths=["old.txt"], pull_request=None))

    assert git(env.repo, "show", "--name-status", "--format=", "HEAD").strip() == "D\told.txt"
    assert published.commit_sha == git(env.repo, "rev-parse", "HEAD").strip()


async def test_without_push_only_a_commit_is_made(env: Env) -> None:
    session = await env.worktree_session()
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    published = await env.publisher.publish(session, env.plan(push=False, pull_request=None))

    assert published.commit_sha is not None
    assert [t for t, _ in await env.events(session.id)] == [types.GIT_COMMITTED]


async def test_nothing_to_commit(env: Env) -> None:
    session = await env.worktree_session()

    with pytest.raises(NothingToCommitError, match="no changes to commit"):
        await env.publisher.publish(session, env.plan())


async def test_work_the_agent_committed_itself_leaves_nothing_to_commit(env: Env) -> None:
    """B58: the review covers what is not committed; the agent pushes its own commits when
    the user asks it to.
    """
    session = await env.worktree_session()
    commit_file(env.worktree, "committed.txt")

    with pytest.raises(NothingToCommitError, match="no changes to commit"):
        await env.publisher.publish(session, env.plan(pull_request=None))

    assert (await env.store.get(session.id)).commit_sha is None
    assert "agent/fix" not in git(env.origin, "for-each-ref")


HOOKS = (
    *("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit", "pre-push"),
    *("reference-transaction", "post-checkout", "pre-auto-gc", "post-index-change"),
)


def plant_hooks(hooks_dir: Path, marker: Path) -> None:
    """Hooks that record that they ran and fail, as an agent could plant them."""
    hooks_dir.mkdir(parents=True, exist_ok=True)
    for name in HOOKS:
        hook = hooks_dir / name
        hook.write_text(f"#!/bin/sh\necho {name} >> '{marker}'\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)


async def test_planted_hooks_never_run_when_publishing(env: Env, tmp_path: Path) -> None:
    """D050: hooks run with the user's credentials, so the daemon runs none."""
    marker = tmp_path / "hooks-ran"
    session = await env.worktree_session()
    plant_hooks(env.repo / ".git" / "hooks", marker)
    plant_hooks(tmp_path / "planted", marker)
    git(env.repo, "config", "core.hooksPath", str(tmp_path / "planted"))
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    published = await env.publisher.publish(session, env.plan())

    assert not marker.exists()
    assert git(env.origin, "rev-parse", "agent/fix").strip() == published.commit_sha


UNSAFE_SETTINGS = [
    ("core.sshCommand", "ssh -o ProxyCommand=evil", "core.sshcommand (runs a program)"),
    ("core.gitProxy", "evil", "core.gitproxy (runs a program)"),
    ("core.fsmonitor", "watch-changes", "core.fsmonitor (runs a program)"),
    ("credential.helper", "!cat >> stolen", "credential.helper (handles your credentials)"),
    (
        "url.https://evil.example/.insteadOf",
        "https://github.com/",
        "url.https://evil.example/.insteadof (rewrites remote URLs)",
    ),
    ("http.proxy", "http://evil:8080", "http.proxy (changes where or how data is sent)"),
    ("remote.origin.receivepack", "evil", "remote.origin.receivepack (runs a program)"),
    ("filter.evil.clean", "evil", "filter.evil.clean (runs a program on your files)"),
    ("gpg.program", "evil", "gpg.program (runs a program)"),
    ("hook.audit.command", "evil", "hook.audit.command (runs a program)"),
    ("protocol.file.allow", "always", "protocol.file.allow (allows other transports)"),
]


@pytest.mark.parametrize(("key", "value", "reported"), UNSAFE_SETTINGS)
async def test_repository_settings_that_run_programs_stop_publishing(
    env: Env, key: str, value: str, reported: str
) -> None:
    """D050: nothing is staged, committed or pushed while such a setting is there."""
    session = await env.worktree_session()
    git(env.repo, "config", key, value)
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    with pytest.raises(UnsafeRepoConfigError) as caught:
        await env.publisher.publish(session, env.plan())

    assert caught.value.status_code == 409
    assert caught.value.payload() == {
        "detail": str(caught.value),
        "code": "unsafe_repo_config",
        "settings": [reported],
    }
    assert reported in str(caught.value)
    assert git(env.worktree, "rev-parse", "HEAD").strip() == env.base
    assert git(env.worktree, "diff", "--cached", "--name-only") == ""
    assert (await env.events(session.id)) == [
        (types.GIT_FAILED, {"step": "commit", "stderr": str(caught.value)})
    ]


async def test_included_and_per_worktree_settings_are_checked_too(env: Env, tmp_path: Path) -> None:
    session = await env.worktree_session()
    included = tmp_path / "included.gitconfig"
    included.write_text("[credential]\n\thelper = evil\n", encoding="utf-8")
    git(env.repo, "config", "include.path", str(included))
    git(env.repo, "config", "extensions.worktreeConfig", "true")
    git(env.worktree, "config", "--worktree", "core.sshCommand", "evil")
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    with pytest.raises(UnsafeRepoConfigError) as caught:
        await env.publisher.publish(session, env.plan())

    assert caught.value.settings == [
        "credential.helper (handles your credentials)",
        "core.sshcommand (runs a program)",
    ]


async def test_ordinary_repository_settings_are_published(env: Env) -> None:
    session = await env.worktree_session()
    for key, value in (
        ("http.postBuffer", "524288000"),
        ("protocol.version", "2"),
        ("core.fsmonitor", "false"),
        ("filter.lfs.clean", "git-lfs clean -- %f"),
        ("filter.lfs.smudge", "git-lfs smudge -- %f"),
        ("filter.lfs.process", "git-lfs filter-process"),
        ("filter.lfs.required", "true"),
        ("pull.rebase", "true"),
    ):
        git(env.repo, "config", key, value)
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    published = await env.publisher.publish(session, env.plan())

    assert git(env.origin, "rev-parse", "agent/fix").strip() == published.commit_sha


async def test_pushing_needs_a_confirmed_remote_url(env: Env) -> None:
    session = await env.worktree_session()
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    with pytest.raises(RemoteNotConfirmedError) as caught:
        await env.publisher.publish(session, env.plan(remote_url=None))

    assert caught.value.status_code == 409
    assert caught.value.payload() == {
        "detail": str(caught.value),
        "code": "remote_not_confirmed",
        "remote_urls": [str(env.origin)],
        "confirmed_url": None,
    }
    assert git(env.worktree, "rev-parse", "HEAD").strip() == env.base
    assert (await env.events(session.id)) == [
        (types.GIT_FAILED, {"step": "push", "stderr": str(caught.value)})
    ]


def bare(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "--bare")
    return path


@pytest.mark.parametrize(
    "change",
    [
        ("remote", "set-url", "origin", "{evil}"),
        ("remote", "set-url", "--push", "origin", "{evil}"),
        ("config", "--add", "remote.origin.pushurl", "{evil}"),
        ("remote", "remove", "origin"),
    ],
)
async def test_a_changed_remote_url_is_refused(
    env: Env, tmp_path: Path, change: tuple[str, ...]
) -> None:
    """D050: the agent cannot send the work to another URL by editing the git config."""
    evil = bare(tmp_path / "evil.git")
    session = await env.worktree_session()
    git(env.repo, *(arg.format(evil=evil) for arg in change))
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    with pytest.raises(RemoteChangedError) as caught:
        await env.publisher.publish(session, env.plan())

    payload = caught.value.payload()
    assert payload["code"] == "remote_changed"
    assert payload["confirmed_url"] == str(env.origin)
    assert payload["remote_urls"] != [str(env.origin)]
    assert str(env.origin) in str(caught.value)
    assert git(evil, "for-each-ref") == ""
    assert git(env.origin, "for-each-ref", "refs/heads/agent") == ""


async def test_pull_requests_name_the_github_repository_of_the_confirmed_remote(
    env: Env,
) -> None:
    url = "git@github.com:me/repo.git"
    session = await env.worktree_session()
    git(env.repo, "remote", "set-url", "origin", url)
    env.runner.outputs["git push"] = ""  # GitHub is not reached in tests
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    await env.publisher.publish(session, env.plan(remote_url=url))

    assert [call[:5] for call in env.runner.gh_calls()] == [
        ("gh", "pr", "create", "--repo", "me/repo")
    ]


def remote_refs(origin: Path) -> str:
    return git(origin, "for-each-ref", "--format=%(objectname) %(refname)")


def push_calls(runner: FakeRunner) -> list[tuple[str, ...]]:
    return [call[call.index("push") :] for call in runner.calls if "push" in call]


@pytest.mark.parametrize("name", ["--mirror", "--delete", "--force", "-u"])
async def test_a_branch_named_like_a_push_option_is_never_pushed(env: Env, name: str) -> None:
    """SEC-01: the agent can point HEAD at such a branch with commands the git guard allows;
    pushed as `git push ... origin --mirror` it would delete and overwrite refs on origin.
    """
    git(env.repo, "push", "-q", "origin", "main:refs/heads/secret")
    git(env.repo, "update-ref", "refs/remotes/origin/elsewhere", "HEAD")
    session = await env.in_place_session()
    git(env.repo, "update-ref", f"refs/heads/{name}", "HEAD")
    git(env.repo, "symbolic-ref", "HEAD", f"refs/heads/{name}")
    (env.repo / "agent.txt").write_text("from the agent\n", encoding="utf-8")
    before = remote_refs(env.origin)

    with pytest.raises(UnsafeBranchError) as caught:
        await env.publisher.publish(session, env.plan(paths=["agent.txt"], pull_request=None))

    assert caught.value.status_code == 409
    assert caught.value.payload() == {
        "detail": str(caught.value),
        "code": "unsafe_branch",
        "branch": name,
    }
    assert repr(name) in str(caught.value)
    assert remote_refs(env.origin) == before
    assert push_calls(env.runner) == []
    # Refused before anything is committed.
    assert git(env.repo, "rev-parse", "HEAD").strip() == env.base
    assert await env.events(session.id) == [
        (types.GIT_FAILED, {"step": "push", "stderr": str(caught.value)})
    ]


@pytest.mark.parametrize(
    ("head", "reported"),
    [("refs/notes/x", "refs/notes/x"), ("refs/heads/HEAD", "HEAD")],
)
async def test_a_checkout_on_anything_but_a_plain_branch_is_not_pushed(
    env: Env, head: str, reported: str
) -> None:
    git(env.repo, "update-ref", head, "HEAD")
    session = await env.in_place_session()
    git(env.repo, "symbolic-ref", "HEAD", head)
    (env.repo / "agent.txt").write_text("from the agent\n", encoding="utf-8")
    before = remote_refs(env.origin)

    with pytest.raises(UnsafeBranchError) as caught:
        await env.publisher.publish(session, env.plan(paths=["agent.txt"], pull_request=None))

    assert caught.value.branch == reported
    assert remote_refs(env.origin) == before
    assert push_calls(env.runner) == []


async def test_pushes_name_the_branch_in_an_explicit_refspec(env: Env) -> None:
    session = await env.in_place_session()
    (env.repo / "agent.txt").write_text("from the agent\n", encoding="utf-8")

    published = await env.publisher.publish(
        session, env.plan(paths=["agent.txt"], pull_request=None)
    )

    assert push_calls(env.runner) == [
        (
            *("push", "--no-verify", "--recurse-submodules=no", "--no-follow-tags"),
            "origin",
            f"{published.commit_sha}:refs/heads/main",
        )
    ]
    assert git(env.origin, "rev-parse", "main").strip() == published.commit_sha
    assert git(env.repo, "rev-parse", "--abbrev-ref", "main@{upstream}").strip() == "origin/main"
    assert (types.GIT_PUSHED, {"remote": "origin", "branch": "main"}) in await env.events(
        session.id
    )


async def test_a_missing_gh_fails_the_pull_request_step(env: Env) -> None:
    session = await env.worktree_session()
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")
    env.runner.failures["gh pr"] = FileNotFoundError("No such file or directory: 'gh'")

    with pytest.raises(GitActionError) as caught:
        await env.publisher.publish(session, env.plan())

    assert caught.value.step == "pr"
    assert "No such file" in caught.value.stderr
    assert (await env.store.get(session.id)).commit_sha is not None


@pytest.mark.parametrize(("name", "users"), [("*", "notes.txt"), ("[ab].txt", "a.txt")])
async def test_wildcards_in_a_chosen_file_name_commit_only_that_file(
    env: Env, name: str, users: str
) -> None:
    """SEC-04: git reads paths as patterns even after `--`; the user's own edit stays out."""
    commit_file(env.repo, users, "the user's\n")
    env.base = git(env.repo, "rev-parse", "HEAD").strip()
    session = await env.in_place_session()
    (env.repo / users).write_text("the user's own edit\n", encoding="utf-8")
    (env.repo / name).write_text("from the agent\n", encoding="utf-8")

    await env.publisher.publish(session, env.plan(paths=[name], pull_request=None))

    assert git(env.repo, "show", "--name-only", "--format=", "HEAD").strip() == name
    assert git(env.repo, "status", "--porcelain").strip() == f"M {users}"


async def test_tags_are_never_pushed_with_the_work(env: Env) -> None:
    """SEC-05: `push.followTags` in the repository's config would push annotated tags."""
    session = await env.worktree_session()
    git(env.repo, "config", "push.followTags", "true")
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")
    env.runner.before["git push"] = lambda: git(env.worktree, "tag", "-a", "-m", "go", "release")

    await env.publisher.publish(session, env.plan(pull_request=None))

    assert "--no-follow-tags" in push_calls(env.runner)[0]
    assert git(env.origin, "tag") == ""


async def test_settings_planted_during_publishing_stop_the_push(env: Env) -> None:
    """SEC-07: the repository's config is checked again right before the push."""
    session = await env.worktree_session()
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")
    env.runner.before["git commit"] = lambda: git(env.repo, "config", "core.sshCommand", "evil")

    with pytest.raises(UnsafeRepoConfigError):
        await env.publisher.publish(session, env.plan())

    assert push_calls(env.runner) == []
    assert git(env.origin, "for-each-ref", "refs/heads/agent") == ""


async def test_a_remote_changed_during_publishing_stops_the_push(env: Env, tmp_path: Path) -> None:
    evil = bare(tmp_path / "evil.git")
    session = await env.worktree_session()
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")
    env.runner.before["git commit"] = lambda: git(
        env.repo, "remote", "set-url", "origin", str(evil)
    )

    with pytest.raises(RemoteChangedError):
        await env.publisher.publish(session, env.plan())

    assert push_calls(env.runner) == []
    assert git(evil, "for-each-ref") == ""


async def test_a_nested_repository_is_never_committed(env: Env) -> None:
    """BUG-65: `git add -A` would commit it as a submodule that points nowhere."""
    session = await env.worktree_session()
    init_repo(env.worktree / "lib")
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    with pytest.raises(NestedRepositoryError) as caught:
        await env.publisher.publish(session, env.plan())

    assert caught.value.status_code == 409
    assert caught.value.payload() == {
        "detail": str(caught.value),
        "code": "nested_repository",
        "paths": ["lib/"],
    }
    assert "lib/" in str(caught.value)
    assert git(env.worktree, "rev-parse", "HEAD").strip() == env.base
    assert git(env.worktree, "diff", "--cached", "--name-only") == ""
    assert push_calls(env.runner) == []


async def test_a_chosen_nested_repository_is_never_committed(env: Env) -> None:
    session = await env.in_place_session()
    init_repo(env.repo / "lib")

    with pytest.raises(NestedRepositoryError):
        await env.publisher.publish(session, env.plan(paths=["lib/"], pull_request=None))

    assert git(env.repo, "rev-parse", "HEAD").strip() == env.base


async def test_a_worktree_switched_to_another_branch_is_not_pushed(env: Env) -> None:
    """SEC-06: the review says the work goes to the worktree's branch, and only there."""
    session = await env.worktree_session()
    git(env.repo, "branch", "deploy")
    git(env.worktree, "symbolic-ref", "HEAD", "refs/heads/deploy")
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")
    before = remote_refs(env.origin)

    with pytest.raises(UnsafeBranchError) as caught:
        await env.publisher.publish(session, env.plan())

    assert caught.value.payload()["code"] == "unsafe_branch"
    assert caught.value.branch == "deploy"
    assert "agent/fix" in str(caught.value)
    assert git(env.repo, "rev-parse", "deploy").strip() == env.base
    assert remote_refs(env.origin) == before


async def test_a_filter_planted_in_a_nested_repository_never_runs_when_publishing(
    env: Env, tmp_path: Path
) -> None:
    """SEC-08: `git add -A` runs `status` inside populated submodules and nested
    repositories, at any depth, with their own config, which the agent can write.
    """
    nested = add_nested_repo(env.repo)
    add_nested_repo(nested, "deep")
    git(env.repo, "-c", "advice.addEmbeddedRepo=false", "add", "lib")
    git(env.repo, "commit", "-q", "-m", "deeper")
    env.base = git(env.repo, "rev-parse", "HEAD").strip()
    session = await env.worktree_session()
    git(tmp_path, "clone", "-q", str(nested), str(env.worktree / "lib"))
    git(tmp_path, "clone", "-q", str(nested / "deep"), str(env.worktree / "lib" / "deep"))
    marker = tmp_path / "filter-ran"
    plant_filter(env.worktree / "lib", marker)
    plant_filter(env.worktree / "lib" / "deep", marker, "deeper")
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    published = await env.publisher.publish(session, env.plan(pull_request=None))

    assert not marker.exists()
    assert git(env.worktree, "show", "--name-only", "--format=", "HEAD").split() == ["a.txt"]
    assert git(env.origin, "rev-parse", "agent/fix").strip() == published.commit_sha


async def test_a_nested_filter_that_cannot_be_switched_off_stops_publishing(
    env: Env, tmp_path: Path
) -> None:
    nested = add_nested_repo(env.repo)
    env.base = git(env.repo, "rev-parse", "HEAD").strip()
    session = await env.in_place_session()
    git(nested, "config", "filter.a=b.clean", "sh -c evil")
    (env.repo / "a.txt").write_text("a\n", encoding="utf-8")

    with pytest.raises(GitActionError, match="cannot be switched off"):
        await env.publisher.publish(session, env.plan(paths=["a.txt"], pull_request=None))

    assert git(env.repo, "rev-parse", "HEAD").strip() == env.base
    assert [t for t, _ in await env.events(session.id)] == [types.GIT_FAILED]


def slip_in_commit(cwd: Path) -> str:
    """A commit put on the checkout's branch with plumbing, as a process the agent left
    running could (SEC-15).
    """
    sha = git(cwd, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "unreviewed").strip()
    git(cwd, "update-ref", "HEAD", sha)
    return sha


async def test_a_commit_slipped_in_after_the_checks_is_never_published(env: Env) -> None:
    """SEC-15: Nest's commit must sit on the HEAD the checks saw."""
    session = await env.worktree_session()
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")
    checked = env.plan()
    env.runner.before["git commit"] = lambda: slip_in_commit(env.worktree)

    with pytest.raises(HeadChangedError) as caught:
        await env.publisher.publish(session, checked)

    assert caught.value.payload()["code"] == "head_changed"
    assert push_calls(env.runner) == []
    assert git(env.origin, "for-each-ref", "refs/heads/agent") == ""
    assert (await env.store.get(session.id)).commit_sha is None
    assert (await env.events(session.id))[-1] == (
        types.GIT_FAILED,
        {"step": "commit", "stderr": str(caught.value)},
    )


async def test_a_root_commit_is_checked_too(tmp_path: Path, env: Env) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    session = await env.store.create(new_session(mode="in_place", cwd=repo, base_ref=None))
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    empty_tree = git(repo, "hash-object", "-t", "tree", "/dev/null").strip()

    def slip_in_root() -> None:
        sha = git(repo, "commit-tree", empty_tree, "-m", "unreviewed").strip()
        git(repo, "update-ref", "HEAD", sha)

    env.runner.before["git commit"] = slip_in_root

    with pytest.raises(HeadChangedError):
        await env.publisher.publish(
            session, plan(paths=["a.txt"], push=False, pull_request=None, head=None)
        )


async def test_only_the_checked_work_is_pushed(env: Env) -> None:
    """SEC-15: the push names Nest's commit, not whatever the branch holds by then."""
    session = await env.worktree_session()
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")
    env.runner.before["git push"] = lambda: slip_in_commit(env.worktree)

    published = await env.publisher.publish(session, env.plan(pull_request=None))

    assert git(env.origin, "rev-parse", "agent/fix").strip() == published.commit_sha
    assert git(env.worktree, "rev-parse", "HEAD^").strip() == published.commit_sha


async def test_every_git_command_of_publishing_is_hardened(env: Env) -> None:
    """SEC-17: the config listing and the remote lookup too."""
    session = await env.worktree_session()
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    await env.publisher.publish(session, env.plan())

    git_calls = [call for call in env.runner.calls if call[0] == "git"]
    assert {call[1 + len(HARDENED)] for call in git_calls} >= {"config", "remote", "push"}
    assert [call for call in git_calls if call[1 : 1 + len(HARDENED)] != HARDENED] == []


@pytest.mark.parametrize(("url", "neutral"), [("git@github.com:me/repo.git", True), (None, False)])
async def test_gh_runs_outside_the_checkout_when_it_knows_the_repository(
    env: Env, url: str | None, neutral: bool
) -> None:
    """SEC-17: gh runs git itself, in the folder it runs in; with --repo it needs none."""
    session = await env.worktree_session()
    if url is not None:
        git(env.repo, "remote", "set-url", "origin", url)
        env.runner.outputs["git push"] = ""  # GitHub is not reached in tests
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")
    seen: list[tuple[str, Path]] = []

    async def recording(argv: Sequence[str], cwd: Path) -> str:
        seen.append((argv[0], cwd))
        return await env.runner(argv, cwd)

    publisher = GitPublisher(recording, env.store, env.bus, env.neutral)
    await publisher.publish(session, env.plan(remote_url=url or str(env.origin)))

    assert [cwd for tool, cwd in seen if tool == "gh"] == [env.neutral if neutral else env.worktree]
    assert {cwd for tool, cwd in seen if tool == "git"} == {env.worktree}
