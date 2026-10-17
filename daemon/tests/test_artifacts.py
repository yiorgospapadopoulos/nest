"""Artifacts (B79): every chat and pixie run saves Markdown or HTML through its `nest`
tools, each update a new version; the history outlives the chat, and events announce it.
"""

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from claude_agent_sdk import ClaudeAgentOptions, PermissionResultAllow, ToolPermissionContext
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
from pydantic import JsonValue

from nestd.artifacts.models import CONTENT_MAX, TITLE_MAX, ArtifactNotFoundError
from nestd.artifacts.tools import ARTIFACT_NOTE, artifact_tools
from nestd.context import AppContext
from nestd.events import types
from nestd.pixies.prompt import PREAMBLE
from nestd.providers.base import AgentTool, PermissionDecision, ToolRefusedError
from nestd.providers.claude import build_options
from nestd.sessions.models import Session, UpdateSession
from nestd.sessions.turns import GUARDED_PROMPT, NEST_PROMPT, PLAIN_FOLDER_PROMPT
from nestd.storage.db import Params, Transaction
from tests.fake_provider import FakeProvider, FakeRun
from tests.fakes import FakeClock
from tests.pixie_nest_support import ctx, idle, make_boss, provider, user_chat
from tests.test_claude_provider import ScriptedHandler

__all__ = ["ctx", "provider"]

type Tools = dict[str, AgentTool]

REPORT = "# Options\n\n| A | B |\n|---|---|\n| fast | safe |\n"


def run_of(provider: FakeProvider, session: Session) -> FakeRun:
    return next(run for run in provider.runs if run.spec.cwd == session.cwd)


def nest_tools(run: FakeRun) -> Tools:
    return {tool.name: tool for tool in run.spec.nest_tools}


async def chat(ctx: AppContext, provider: FakeProvider, repo: str = "web") -> tuple[Session, Tools]:
    session = await user_chat(ctx, provider, repo)
    return session, nest_tools(run_of(provider, session))


async def create(tools: Tools, **args: JsonValue) -> str:
    """The new artifact's id, read from the tool's answer."""
    text = await tools["create_artifact"].handler(
        {"title": "Options", "kind": "markdown", "content": REPORT, **args}
    )
    return text.split()[2]


async def refused(tools: Tools, tool: str, **args: JsonValue) -> str:
    with pytest.raises(ToolRefusedError) as refusal:
        await tools[tool].handler(args)
    return str(refusal.value)


async def published(ctx: AppContext, event_type: str) -> list[dict[str, Any]]:
    rows = await ctx.db.fetch_all(
        "SELECT payload FROM events WHERE type = ? ORDER BY id", (event_type,)
    )
    return [json.loads(row["payload"]) for row in rows]


async def cards(ctx: AppContext, session_id: str) -> list[dict[str, JsonValue]]:
    events = await ctx.bus.session_events(session_id)
    return [dict(e.payload) for e in events if e.type == types.SESSION_ARTIFACT]


def folder(ctx: AppContext, artifact_id: str) -> Path:
    return ctx.paths.artifacts_dir / artifact_id


async def test_every_chat_run_gets_the_artifact_tools(
    ctx: AppContext, provider: FakeProvider
) -> None:
    session, tools = await chat(ctx, provider)
    run = run_of(provider, session)

    assert [tool.name for tool in run.spec.nest_tools] == ["create_artifact", "update_artifact"]
    assert run.spec.tools == ()
    assert ARTIFACT_NOTE in (run.spec.system_prompt_append or "")
    assert tools["create_artifact"].schema["required"] == ["title", "kind", "content"]


def test_every_prompt_tells_the_agent_about_artifacts() -> None:
    for prompt in (NEST_PROMPT, PLAIN_FOLDER_PROMPT, GUARDED_PROMPT):
        assert prompt.endswith(ARTIFACT_NOTE)
    assert "long report, summary, comparison or plan" in ARTIFACT_NOTE
    assert "instead of a long chat message or a file in the repository" in ARTIFACT_NOTE
    assert "as an artifact with create_artifact" in PREAMBLE


async def test_creating_saves_the_first_version_and_announces_it(
    ctx: AppContext, provider: FakeProvider
) -> None:
    session, tools = await chat(ctx, provider)

    answer = await tools["create_artifact"].handler(
        {"title": "  Options\n compared ", "kind": "markdown", "content": REPORT}
    )

    [artifact] = await ctx.artifacts.list_artifacts()
    assert answer == (
        f"Saved artifact {artifact.id} (version 1): Options compared. The user opens it from"
        " the card in this chat; to change it, call update_artifact with this id."
    )
    assert (folder(ctx, artifact.id) / "v1.md").read_text(encoding="utf-8") == REPORT
    assert artifact.model_dump(exclude={"id", "created_at", "updated_at"}) == {
        "title": "Options compared",
        "kind": "markdown",
        "repo": "web",
        "session_id": session.id,
        "chat_title": session.title,
        "chat_deleted": False,
        "pixie_id": None,
        "pixie_name": None,
        "latest_version": 1,
        "version_count": 1,
        "seen": False,
    }
    assert await cards(ctx, session.id) == [
        {
            "artifact_id": artifact.id,
            "version": 1,
            "title": "Options compared",
            "kind": "markdown",
            "action": "created",
        }
    ]
    assert await published(ctx, types.ARTIFACT_SAVED) == [
        {
            "artifact": artifact.model_dump(mode="json"),
            "action": "created",
            "version": 1,
            "unseen": 1,
        }
    ]
    assert await ctx.artifacts.unseen() == 1


async def test_updating_adds_a_version_and_keeps_the_earlier_ones(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    session, tools = await chat(ctx, provider)
    artifact_id = await create(tools, kind="html", content="<h1>v1</h1>")
    await ctx.artifacts.mark_seen(artifact_id)
    clock.advance(timedelta(minutes=5))

    renamed = await tools["update_artifact"].handler(
        {"artifact_id": artifact_id, "content": "<h1>v2</h1>", "title": "Plan"}
    )
    kept = await tools["update_artifact"].handler(
        {"artifact_id": artifact_id, "content": "<h1>v3</h1>"}
    )

    detail = await ctx.artifacts.detail(artifact_id)
    first = await ctx.artifacts.content(artifact_id, 1)
    assert renamed == f"Saved version 2 of artifact {artifact_id}: Plan."
    assert kept == f"Saved version 3 of artifact {artifact_id}: Plan."
    assert sorted(p.name for p in folder(ctx, artifact_id).iterdir()) == [
        "v1.html",
        "v2.html",
        "v3.html",
    ]
    assert [(v.version, v.title, v.size) for v in detail.versions] == [
        (1, "Options", 11),
        (2, "Plan", 11),
        (3, "Plan", 11),
    ]
    assert (detail.title, detail.latest_version, detail.version_count) == ("Plan", 3, 3)
    assert detail.updated_at == clock.now()
    assert detail.created_at == clock.now() - timedelta(minutes=5)
    # A new version is new to the user again.
    assert detail.seen is False
    assert (first.content, first.title, first.kind, first.version) == (
        "<h1>v1</h1>",
        "Options",
        "html",
        1,
    )
    assert [c["action"] for c in await cards(ctx, session.id)] == ["created", "updated", "updated"]
    saved = await published(ctx, types.ARTIFACT_SAVED)
    assert [(s["action"], s["version"], s["unseen"]) for s in saved] == [
        ("created", 1, 1),
        ("updated", 2, 1),
        ("updated", 3, 1),
    ]


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"title": "T", "kind": "pdf", "content": "x"}, "kind: Input should be 'markdown' or"),
        ({"title": "T", "kind": "markdown"}, "content: Field required."),
        ({"title": " \n", "kind": "markdown", "content": "x"}, "an artifact needs a title"),
        (
            {"title": "T" * (TITLE_MAX + 1), "kind": "markdown", "content": "x"},
            f"an artifact's title has at most {TITLE_MAX} characters",
        ),
        ({"title": "T", "kind": "markdown", "content": "  \n"}, "an artifact needs content"),
        (
            {"title": "T", "kind": "markdown", "content": "é" * (CONTENT_MAX // 2 + 1)},
            f"the content is {CONTENT_MAX + 2} bytes; an artifact version has at most"
            f" {CONTENT_MAX} bytes (1 MiB)",
        ),
        (
            {"title": "T", "kind": "markdown", "content": "half \ud800"},
            "the content is not valid text",
        ),
    ],
)
async def test_creating_refuses_bad_input_and_saves_nothing(
    ctx: AppContext, provider: FakeProvider, args: dict[str, JsonValue], reason: str
) -> None:
    _, tools = await chat(ctx, provider)

    message = await refused(tools, "create_artifact", **args)

    assert reason in message
    assert await ctx.artifacts.list_artifacts() == []
    assert list(ctx.paths.artifacts_dir.iterdir()) == []
    assert await published(ctx, types.ARTIFACT_SAVED) == []


async def test_content_of_exactly_the_limit_is_saved(
    ctx: AppContext, provider: FakeProvider
) -> None:
    _, tools = await chat(ctx, provider)

    artifact_id = await create(tools, content="a" * CONTENT_MAX)

    assert (await ctx.artifacts.detail(artifact_id)).versions[0].size == CONTENT_MAX


async def test_updating_refuses_unknown_foreign_and_bad_versions(
    ctx: AppContext, provider: FakeProvider
) -> None:
    session, tools = await chat(ctx, provider)
    other, other_tools = await chat(ctx, provider, "api")
    theirs = await create(other_tools)

    unknown = await refused(tools, "update_artifact", artifact_id="nope", content="x")
    foreign = await refused(tools, "update_artifact", artifact_id=theirs, content="x")
    no_content = await refused(tools, "update_artifact", artifact_id=theirs)
    too_big = await refused(
        other_tools, "update_artifact", artifact_id=theirs, content="a" * (CONTENT_MAX + 1)
    )
    bad_title = await refused(
        other_tools, "update_artifact", artifact_id=theirs, content="x", title=" "
    )

    assert unknown == "unknown artifact 'nope'"
    assert foreign == (f"artifact {theirs!r} belongs to another chat; create a new one instead")
    assert no_content == "content: Field required."
    assert "an artifact version has at most" in too_big
    assert bad_title == "an artifact needs a title"
    assert (await ctx.artifacts.detail(theirs)).version_count == 1
    assert await cards(ctx, session.id) == []
    assert len(await cards(ctx, other.id)) == 1


async def test_a_pixie_runs_artifacts_are_kept_with_the_pixie(
    ctx: AppContext, provider: FakeProvider
) -> None:
    boss = await make_boss(ctx, provider)
    chat_session = await idle(ctx, boss.chat_id)
    run = run_of(provider, chat_session)
    tools = nest_tools(run)
    artifact_id = await create(tools, title="Weekly habits")
    # Another run of the same pixie, such as a habit run, may update it.
    habit_run = chat_session.model_copy(update={"id": "habit-session"})
    again = {t.name: t for t in artifact_tools(ctx.artifacts, habit_run)}
    await again["update_artifact"].handler({"artifact_id": artifact_id, "content": "week 2"})

    [artifact] = await ctx.artifacts.list_artifacts(pixie_id=boss.pixie.id)
    assert "create_artifact" not in {tool.name for tool in run.spec.tools}
    assert "as an artifact with create_artifact" in (run.spec.system_prompt_append or "")
    assert (artifact.id, artifact.pixie_id, artifact.pixie_name) == (
        artifact_id,
        boss.pixie.id,
        "Boss",
    )
    assert (artifact.session_id, artifact.repo) == (boss.chat_id, f"pixie:{boss.pixie.id}")
    assert artifact.version_count == 2
    assert [c["action"] for c in await cards(ctx, boss.chat_id)] == ["created"]

    await ctx.pixies.delete(boss.pixie.id)

    [kept] = await ctx.artifacts.list_artifacts(pixie_id=boss.pixie.id)
    assert (kept.pixie_name, kept.chat_deleted) == ("Boss", True)


async def test_a_deleted_chat_keeps_its_artifacts(ctx: AppContext, provider: FakeProvider) -> None:
    session, tools = await chat(ctx, provider)
    artifact_id = await create(tools)
    await ctx.sessions.update(session.id, UpdateSession(title="Renamed chat"))

    await ctx.sessions.purge(session.id)

    [artifact] = await ctx.artifacts.list_artifacts(repo="web")
    assert (artifact.id, artifact.session_id) == (artifact_id, session.id)
    assert (artifact.chat_title, artifact.chat_deleted) == ("Renamed chat", True)
    assert (await ctx.artifacts.content(artifact_id, 1)).content == REPORT


async def test_deleting_removes_rows_and_files(ctx: AppContext, provider: FakeProvider) -> None:
    _, tools = await chat(ctx, provider)
    gone = await create(tools)
    await tools["update_artifact"].handler({"artifact_id": gone, "content": "v2"})
    kept = await create(tools, title="Kept")

    await ctx.artifacts.delete(gone)

    assert [a.id for a in await ctx.artifacts.list_artifacts()] == [kept]
    assert not folder(ctx, gone).exists()
    assert folder(ctx, kept).exists()
    versions = await ctx.db.fetch_all(
        "SELECT * FROM artifact_versions WHERE artifact_id = ?", (gone,)
    )
    assert versions == []
    assert await published(ctx, types.ARTIFACT_DELETED) == [{"artifact_id": gone, "unseen": 1}]
    with pytest.raises(ArtifactNotFoundError):
        await ctx.artifacts.delete(gone)
    with pytest.raises(ArtifactNotFoundError):
        await ctx.artifacts.detail(gone)


async def test_seen_is_announced_once(ctx: AppContext, provider: FakeProvider) -> None:
    _, tools = await chat(ctx, provider)
    first = await create(tools)
    await create(tools, title="Second")

    seen = await ctx.artifacts.mark_seen(first)
    again = await ctx.artifacts.mark_seen(first)

    assert (seen.seen, again.seen) == (True, True)
    assert await published(ctx, types.ARTIFACT_SEEN) == [{"artifact_id": first, "unseen": 1}]
    assert await ctx.artifacts.unseen() == 1
    with pytest.raises(ArtifactNotFoundError):
        await ctx.artifacts.mark_seen("nope")


async def test_lists_filter_and_put_the_latest_update_first(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    web, web_tools = await chat(ctx, provider)
    api, api_tools = await chat(ctx, provider, "api")
    older = await create(web_tools, title="Older")
    clock.advance(timedelta(minutes=1))
    other = await create(api_tools, title="Other")
    clock.advance(timedelta(minutes=1))
    await web_tools["update_artifact"].handler({"artifact_id": older, "content": "new"})

    every = await ctx.artifacts.list_artifacts()
    in_api = await ctx.artifacts.list_artifacts(repo="api")
    of_web = await ctx.artifacts.list_artifacts(session_id=web.id)
    of_pixie = await ctx.artifacts.list_artifacts(pixie_id="p1")

    assert [a.id for a in every] == [older, other]
    assert [a.id for a in in_api] == [other]
    assert [a.session_id for a in in_api] == [api.id]
    assert [a.id for a in of_web] == [older]
    assert of_pixie == []


async def test_a_missing_version_or_file_is_not_found(
    ctx: AppContext, provider: FakeProvider
) -> None:
    _, tools = await chat(ctx, provider)
    artifact_id = await create(tools)

    with pytest.raises(ArtifactNotFoundError, match="has no version 2"):
        await ctx.artifacts.content(artifact_id, 2)
    (folder(ctx, artifact_id) / "v1.md").unlink()
    with pytest.raises(ArtifactNotFoundError, match=r"the file of version 1 .* is missing"):
        await ctx.artifacts.content(artifact_id, 1)


def fail_saving_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every version's row fails to save, as on a full disk."""
    execute = Transaction.execute

    async def failing(tx: Transaction, sql: str, params: Params = ()) -> int:
        if sql.startswith("INSERT INTO artifact_versions"):
            raise OSError("disk full")
        return await execute(tx, sql, params)

    monkeypatch.setattr(Transaction, "execute", failing)


async def test_a_failed_save_leaves_no_file(
    ctx: AppContext, provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, tools = await chat(ctx, provider)
    artifact_id = await create(tools)

    fail_saving_versions(monkeypatch)
    with pytest.raises(OSError, match="disk full"):
        await tools["update_artifact"].handler({"artifact_id": artifact_id, "content": "v2"})
    with pytest.raises(OSError, match="disk full"):
        await create(tools, title="Never")

    monkeypatch.undo()
    assert [p.name for p in ctx.paths.artifacts_dir.iterdir()] == [artifact_id]
    assert [p.name for p in folder(ctx, artifact_id).iterdir()] == ["v1.md"]
    assert (await ctx.artifacts.detail(artifact_id)).version_count == 1


def cli_mcp_config(options: ClaudeAgentOptions, cli: Path) -> tuple[dict[str, Any], list[str]]:
    """The `--mcp-config` the SDK hands Claude Code, and the whole command."""
    command = SubprocessCLITransport("", replace(options, cli_path=cli))._build_command()  # pyright: ignore[reportPrivateUsage]
    return json.loads(command[command.index("--mcp-config") + 1]), command


async def options_of(run: FakeRun, tmp_path: Path) -> ClaudeAgentOptions:
    return build_options(run.spec, ScriptedHandler(PermissionDecision("deny")), tmp_path / "gh")


async def test_a_chats_options_serve_and_allow_the_artifact_tools(
    ctx: AppContext, provider: FakeProvider, tmp_path: Path
) -> None:
    session = await user_chat(ctx, provider)
    options = await options_of(run_of(provider, session), tmp_path)
    assert options.can_use_tool is not None

    config, command = cli_mcp_config(options, tmp_path / "claude")
    from_subagent = await options.can_use_tool(
        "mcp__nest__create_artifact", {}, ToolPermissionContext(agent_id="a1")
    )

    assert list(cast(dict[str, Any], options.mcp_servers)) == ["nest"]
    assert config == {"mcpServers": {"nest": {"type": "sdk", "name": "nest"}}}
    # The user's own MCP servers still load: no strict MCP config.
    assert "--strict-mcp-config" not in command
    assert options.allowed_tools == ["mcp__nest__create_artifact", "mcp__nest__update_artifact"]
    assert isinstance(from_subagent, PermissionResultAllow)


async def test_a_pixie_runs_options_serve_both_servers(
    ctx: AppContext, provider: FakeProvider, tmp_path: Path
) -> None:
    boss = await make_boss(ctx, provider)
    run = run_of(provider, await idle(ctx, boss.chat_id))
    options = await options_of(run, tmp_path)

    config, _ = cli_mcp_config(options, tmp_path / "claude")

    assert list(config["mcpServers"]) == ["pixie", "nest"]
    assert options.allowed_tools == ["mcp__nest__create_artifact", "mcp__nest__update_artifact"]
    assert options.hooks is not None
    own_guard = next(m for m in options.hooks["PreToolUse"] if "mcp__pixie__" in (m.matcher or ""))
    assert "mcp__nest__" not in (own_guard.matcher or "")
