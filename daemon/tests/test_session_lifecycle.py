import base64
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.config.models import WorktreeConfig
from harness.errors import InvalidInputError
from harness.events import types
from harness.providers.base import ImageInput, ModelOption, UserInput
from harness.sessions.errors import (
    DirtyCheckoutError,
    NoWorkspaceError,
    SessionClosedError,
    SessionNotFoundError,
)
from harness.sessions.models import SessionState
from harness.sessions.turns import HARNESS_PROMPT
from harness.storage.db import Database
from tests.async_support import until
from tests.fake_provider import crash, reply
from tests.fakes import FakeClock
from tests.git_support import git
from tests.session_support import DEFAULTS, Env


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    yield environment
    await environment.manager.shutdown()


async def test_worktree_session_runs_its_first_turn(env: Env) -> None:
    await env.register()
    env.provider.script(reply("Done."))

    created = await env.create()
    session = await env.reach(created.id, SessionState.IDLE)

    assert created.state is SessionState.STARTING
    assert created.title == "Fix the bug"
    assert created.mode == "worktree"
    assert created.provider == "fake"
    assert (created.model, created.effort, created.permission_mode) == (
        "claude-sonnet-5",
        "medium",
        "acceptEdits",
    )
    assert session.worktree_path == (
        env.repo_path.resolve() / ".claude" / "worktrees" / f"harness-{created.id[:8]}"
    )
    assert session.cwd == session.worktree_path
    assert session.branch is not None
    assert session.branch.startswith("agent/fix-the-bug-")
    assert session.base_ref == git(env.repo_path, "rev-parse", "main").strip()
    assert session.provider_session_id == "sdk-1"
    (run,) = env.provider.runs
    assert run.spec.cwd == session.cwd
    assert run.spec.model == "claude-sonnet-5"
    assert run.spec.effort == "medium"
    assert run.spec.permission_mode == "acceptEdits"
    assert run.spec.resume_id is None
    assert run.spec.extra_dirs == ()
    assert run.spec.system_prompt_append == HARNESS_PROMPT
    # Claude Code tells SDK hosts which MCP servers need sign-in; replies should still
    # read like the Claude app's, which does not list them unprompted.
    assert "MCP servers" in HARNESS_PROMPT
    assert "only when the user asks" in HARNESS_PROMPT
    assert run.inputs == [UserInput(text="Fix the bug\nDetails here")]
    assert await env.event_types(created.id) == [
        types.SESSION_CREATED,
        types.SESSION_STATE,
        types.SESSION_WORKSPACE,
        types.SESSION_USER_MESSAGE,
        types.SESSION_STATE,
        types.SESSION_MESSAGE,
        types.SESSION_RESULT,
        types.SESSION_STATE,
    ]
    assert await env.states(created.id) == ["starting", "running", "idle"]
    events = await env.bus.session_events(created.id)
    assert events[0].payload["session"] == created.model_dump(mode="json")
    assert events[2].payload == {
        "path": str(session.worktree_path),
        "branch": session.branch,
        "base_ref": session.base_ref,
        "linked": [],
        "missing": [],
        "existing": [],
        "failed": [],
    }
    assert events[3].payload == {"text": "Fix the bug\nDetails here", "attachments": []}


async def test_request_overrides_defaults_and_title(env: Env) -> None:
    await env.register()
    env.provider.script(reply("ok"))

    created = await env.create(
        title="Custom", model="claude-opus-5", effort="max", permission_mode="plan"
    )
    await env.reach(created.id, SessionState.IDLE)

    assert created.title == "Custom"
    spec = env.provider.runs[0].spec
    assert (spec.model, spec.effort, spec.permission_mode) == ("claude-opus-5", "max", "plan")


async def test_new_sessions_follow_the_global_mode_unless_the_repo_sets_one(env: Env) -> None:
    await env.register()
    env.provider.script(reply("ok"), reply("ok"), reply("ok"))
    env.defaults = DEFAULTS.model_copy(update={"default_mode": "in_place"})

    global_default = await env.create()
    env.repos.update_worktree_config("repo", WorktreeConfig(default=True))
    repo_override = await env.create()
    explicit = await env.create(mode="in_place", allow_dirty=True)

    assert global_default.mode == "in_place"
    assert repo_override.mode == "worktree"
    assert explicit.mode == "in_place"


async def test_defaults_are_read_for_each_new_session(env: Env) -> None:
    await env.register()
    env.provider.script(reply("ok"))
    env.defaults = DEFAULTS.model_copy(
        update={"model": "opus", "effort": "xhigh", "permission_mode": "plan"}
    )

    created = await env.create()

    assert (created.model, created.effort, created.permission_mode) == ("opus", "xhigh", "plan")


def models(*entries: tuple[str, list[str]]) -> list[ModelOption]:
    return [
        ModelOption(
            value=value,
            display_name=value.capitalize(),
            description="",
            effort_levels=levels,
            supports_effort=bool(levels),
        )
        for value, levels in entries
    ]


async def test_an_effort_the_model_does_not_take_is_refused(env: Env) -> None:
    await env.register()
    env.models = models(("haiku", []), ("claude-opus-4-6", ["low", "high", "max"]))

    with pytest.raises(InvalidInputError, match="Haiku does not take a thinking level"):
        await env.create(model="haiku", effort="low")
    with pytest.raises(InvalidInputError, match="low, high, max"):
        await env.create(model="claude-opus-4-6", effort="xhigh")

    assert await env.store.list_sessions() == []


async def test_a_default_effort_the_model_does_not_take_is_left_out(env: Env) -> None:
    await env.register()
    env.provider.script(reply("ok"), reply("ok"), reply("ok"))
    env.models = models(("haiku", []), ("opus", ["low", "medium"]))

    haiku = await env.create(model="haiku")
    opus = await env.create(model="opus", effort="low")
    unknown = await env.create(model="claude-opus-4-1")

    assert (haiku.model, haiku.effort) == ("haiku", None)
    assert (opus.model, opus.effort) == ("opus", "low")
    # Models the engine does not list are not checked.
    assert (unknown.model, unknown.effort) == ("claude-opus-4-1", "medium")


async def test_the_default_model_is_checked_as_claude_codes_default(env: Env) -> None:
    await env.register()
    env.provider.script(reply("ok"))
    env.defaults = DEFAULTS.model_copy(update={"model": None, "effort": "max"})
    env.models = models(("default", ["low", "high"]))

    created = await env.create()

    assert (created.model, created.effort) == (None, None)


async def test_long_prompts_get_a_short_title(env: Env) -> None:
    await env.register()
    env.provider.script(reply("ok"))

    created = await env.create(prompt="  " + "word " * 40)

    assert created.title == "Word" + " word" * 8


async def test_in_place_session_uses_the_checkout(env: Env) -> None:
    await env.register(WorktreeConfig(default=False))
    env.provider.script(reply("ok"))

    created = await env.create()
    session = await env.reach(created.id, SessionState.IDLE)

    assert created.mode == "in_place"
    assert session.cwd == env.repo_path.resolve()
    assert session.worktree_path is None
    assert session.branch is None
    assert types.SESSION_WORKSPACE not in await env.event_types(created.id)


async def test_in_place_refuses_a_dirty_checkout_unless_allowed(env: Env) -> None:
    await env.register()
    (env.repo_path / "README.md").write_text("changed", encoding="utf-8")
    env.provider.script(reply("ok"))

    with pytest.raises(DirtyCheckoutError) as caught:
        await env.create(mode="in_place")
    created = await env.create(mode="in_place", allow_dirty=True)

    assert caught.value.files == ["README.md"]
    assert caught.value.payload() == {
        "detail": "the checkout has uncommitted changes; set allow_dirty to proceed",
        "files": ["README.md"],
    }
    await env.reach(created.id, SessionState.IDLE)


async def test_create_validates_repo_and_attachments(env: Env) -> None:
    await env.register()

    with pytest.raises(InvalidInputError, match="unknown repo 'nope'"):
        await env.create(repo="nope")
    with pytest.raises(InvalidInputError, match="unknown attachment"):
        await env.create(attachment_ids=["missing"])
    assert await env.manager.list_sessions() == []


async def test_links_are_reported_with_the_workspace(env: Env) -> None:
    await env.register(WorktreeConfig(link=[".env", "absent.env"]))
    (env.repo_path / ".env").write_text("A=1", encoding="utf-8")
    env.provider.script(reply("ok"))

    created = await env.create()
    session = await env.reach(created.id, SessionState.IDLE)

    workspace = next(
        e for e in await env.bus.session_events(created.id) if e.type == types.SESSION_WORKSPACE
    )
    assert workspace.payload["linked"] == [".env"]
    assert workspace.payload["missing"] == ["absent.env"]
    assert session.cwd is not None
    assert (session.cwd / ".env").is_symlink()


async def test_setup_failure_fails_the_session_without_starting_the_agent(env: Env) -> None:
    await env.register(WorktreeConfig(setup=["exit 7"]))

    created = await env.create()
    session = await env.reach(created.id, SessionState.FAILED)

    assert env.provider.runs == []
    assert session.last_error == "setup command failed: exit 7"
    failed = next(
        e for e in await env.bus.session_events(created.id) if e.type == types.SESSION_SETUP_FAILED
    )
    assert failed.payload == {
        "command": "exit 7",
        "exit_code": 7,
        "timed_out": False,
        "log_path": str(env.paths.logs_dir / f"setup-{created.id}.log"),
    }
    assert await env.states(created.id) == ["starting", "failed"]


async def test_worktree_errors_fail_the_session(env: Env, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q", "-b", "main")
    await env.repos.register(empty)

    created = await env.create(repo="empty")
    session = await env.reach(created.id, SessionState.FAILED)

    assert session.last_error is not None
    assert "rev-parse" in session.last_error
    assert session.cwd is None
    with pytest.raises(NoWorkspaceError, match="no working directory"):
        await env.manager.send(created.id, "hello", [])


async def test_follow_up_reuses_the_run(env: Env) -> None:
    await env.register()
    env.provider.script(reply("one"), reply("two"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    await env.manager.send(created.id, "and then?", [])
    await until_turns(env, created.id, 2)

    (run,) = env.provider.runs
    assert run.inputs[1] == UserInput(text="and then?")
    assert (await env.states(created.id))[-2:] == ["running", "idle"]


async def until_turns(env: Env, session_id: str, count: int) -> None:
    async def done() -> bool:
        events = await env.bus.session_events(session_id)
        results = [e for e in events if e.type == types.SESSION_RESULT]
        states = [e.payload["state"] for e in events if e.type == types.SESSION_STATE]
        return len(results) == count and states[-1] == "idle"

    await until(done)


async def test_attachments_reach_the_agent_and_reopen_the_run_for_new_dirs(env: Env) -> None:
    await env.register()
    env.provider.script(reply("one"), reply("two", "sdk-2"), reply("three", "sdk-2"))
    image = await env.attachments.save("shot.png", b"\x89PNG", "image/png")
    created = await env.create(attachment_ids=[image.id])
    await env.reach(created.id, SessionState.IDLE)
    doc = await env.attachments.save("spec.pdf", b"%PDF", "application/pdf")

    await env.manager.send(created.id, "read this", [doc.id])
    await until_turns(env, created.id, 2)
    await env.manager.send(created.id, "again", [doc.id])
    await until_turns(env, created.id, 3)

    first, second = env.provider.runs
    assert first.inputs == [
        UserInput(
            text="Fix the bug\nDetails here",
            images=(ImageInput("image/png", base64.b64encode(b"\x89PNG").decode()),),
        )
    ]
    assert first.closed is True
    assert second.spec.resume_id == "sdk-1"
    assert second.spec.extra_dirs == (doc.path.parent,)
    assert second.inputs == [
        UserInput(text="read this", file_paths=(doc.path,)),
        UserInput(text="again", file_paths=(doc.path,)),
    ]
    messages = [
        e.payload
        for e in await env.bus.session_events(created.id)
        if e.type == types.SESSION_USER_MESSAGE
    ]
    assert messages[1] == {
        "text": "read this",
        "attachments": [
            {"id": doc.id, "filename": "spec.pdf", "media_type": "application/pdf", "size": 4}
        ],
    }


async def test_send_queues_during_setup_and_rejects_closed_and_unknown_sessions(env: Env) -> None:
    await env.register(WorktreeConfig(setup=["sleep 30"]))
    created = await env.create()

    queued = await env.manager.send(created.id, "hi", [])
    await env.manager.close(created.id, remove_worktree=True)

    assert queued.queued_message is not None
    assert await env.manager.queued(created.id) == []
    with pytest.raises(SessionClosedError, match="closed"):
        await env.manager.send(created.id, "hi", [])
    with pytest.raises(SessionNotFoundError):
        await env.manager.send("nope", "hi", [])


async def test_provider_errors_fail_the_turn_and_the_next_message_resumes(env: Env) -> None:
    await env.register()
    env.provider.script(reply("one"), crash("cli crashed"), reply("back"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    await env.manager.send(created.id, "break", [])
    failed = await env.reach(created.id, SessionState.FAILED)
    await env.manager.send(created.id, "retry", [])
    await env.reach(created.id, SessionState.IDLE)

    assert failed.last_error == "cli crashed"
    first, second = env.provider.runs
    assert first.closed is True
    assert second.spec.resume_id == "sdk-1"


async def test_opening_errors_fail_the_session(env: Env) -> None:
    await env.register()
    env.provider.open_error = RuntimeError("claude not found")

    created = await env.create()
    session = await env.reach(created.id, SessionState.FAILED)

    assert session.last_error == "claude not found"


async def test_list_and_get(env: Env) -> None:
    await env.register()
    env.provider.script(reply("a"), reply("b"))
    first = await env.create()
    second = await env.create()
    await env.reach(first.id, SessionState.IDLE)
    await env.reach(second.id, SessionState.IDLE)

    assert [s.id for s in await env.manager.list_sessions()] == [second.id, first.id]
    assert (await env.manager.get(first.id)).id == first.id
