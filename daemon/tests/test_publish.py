from pathlib import Path

import pytest

from harness.events import types
from harness.events.bus import EventBus
from harness.gitops.runner import CommandError
from harness.review.errors import GitActionError, NothingToCommitError
from harness.review.publish import GitPublisher, PublishPlan, PullRequest
from harness.sessions.models import Session
from harness.sessions.store import SessionStore
from harness.storage.db import Database
from tests.fake_runner import PR_URL, FakeRunner
from tests.fakes import FakeClock
from tests.git_support import commit_file, git, init_repo, with_origin
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
        self.publisher = GitPublisher(self.runner, self.store, self.bus)

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

    async def events(self, session_id: str) -> list[tuple[str, object]]:
        return [(e.type, e.payload) for e in await self.bus.session_events(session_id)]


@pytest.fixture
def env(tmp_path: Path, db: Database, clock: FakeClock) -> Env:
    return Env(tmp_path, db, clock)


def plan(**fields: object) -> PublishPlan:
    values: dict[str, object] = {
        "message": "Fix the bug",
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

    published = await env.publisher.publish(session, plan())

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
        await env.publisher.publish(session, plan())
    failed = await env.store.get(session.id)
    retried = await env.publisher.publish(failed, plan())
    again = await env.publisher.publish(retried, plan())

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
        plan(
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

    published = await env.publisher.publish(session, plan(paths=["old.txt"], pull_request=None))

    assert git(env.repo, "show", "--name-status", "--format=", "HEAD").strip() == "D\told.txt"
    assert published.commit_sha == git(env.repo, "rev-parse", "HEAD").strip()


async def test_without_push_only_a_commit_is_made(env: Env) -> None:
    session = await env.worktree_session()
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    published = await env.publisher.publish(session, plan(push=False, pull_request=None))

    assert published.commit_sha is not None
    assert [t for t, _ in await env.events(session.id)] == [types.GIT_COMMITTED]


async def test_nothing_to_commit(env: Env) -> None:
    session = await env.worktree_session()

    with pytest.raises(NothingToCommitError, match="no changes to commit"):
        await env.publisher.publish(session, plan())


async def test_work_the_agent_committed_itself_is_published_as_is(env: Env) -> None:
    session = await env.worktree_session()
    sha = commit_file(env.worktree, "sneaky.txt")

    published = await env.publisher.publish(session, plan(pull_request=None))

    assert published.commit_sha == sha
    assert git(env.origin, "rev-parse", "agent/fix").strip() == sha


async def test_commit_hooks_run_and_can_stop_the_commit(env: Env) -> None:
    session = await env.worktree_session()
    hook = env.repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'lint failed' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")

    with pytest.raises(GitActionError) as caught:
        await env.publisher.publish(session, plan())

    assert caught.value.step == "commit"
    assert "lint failed" in caught.value.stderr
    assert (await env.store.get(session.id)).commit_sha is None


async def test_a_missing_gh_fails_the_pull_request_step(env: Env) -> None:
    session = await env.worktree_session()
    (env.worktree / "a.txt").write_text("a\n", encoding="utf-8")
    env.runner.failures["gh pr"] = FileNotFoundError("No such file or directory: 'gh'")

    with pytest.raises(GitActionError) as caught:
        await env.publisher.publish(session, plan())

    assert caught.value.step == "pr"
    assert "No such file" in caught.value.stderr
    assert (await env.store.get(session.id)).commit_sha is not None
