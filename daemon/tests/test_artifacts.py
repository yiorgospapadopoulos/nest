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

from nestd.artifacts import templates
from nestd.artifacts.models import (
    CONTENT_MAX,
    TITLE_MAX,
    ArtifactNotFoundError,
    InvalidArtifactError,
    StaleVersionError,
)
from nestd.artifacts.tools import ARTIFACT_NOTE, ASK_SHAPE, USAGE_SHAPE, artifact_tools
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

ALLOWED = [
    "mcp__nest__artifact_guide",
    "mcp__nest__create_artifact",
    "mcp__nest__read_artifact",
    "mcp__nest__update_artifact",
]
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

    assert [tool.name for tool in run.spec.nest_tools] == [
        "create_artifact",
        "update_artifact",
        "read_artifact",
        "artifact_guide",
    ]
    assert run.spec.tools == ()
    assert ARTIFACT_NOTE in (run.spec.system_prompt_append or "")
    assert tools["create_artifact"].schema["required"] == ["title", "kind", "content"]


def test_every_prompt_tells_the_agent_about_artifacts() -> None:
    for prompt in (NEST_PROMPT, PLAIN_FOLDER_PROMPT, GUARDED_PROMPT):
        assert prompt.endswith(ARTIFACT_NOTE)
    assert "long report, summary, comparison or plan" in ARTIFACT_NOTE
    assert "instead of a long chat message or a file in the repository" in ARTIFACT_NOTE
    assert "as an artifact with create_artifact" in PREAMBLE
    # A pixie reads what a page may do in the tool's description.
    assert "follows the rules of its content field" in PREAMBLE
    for text in (ARTIFACT_NOTE, PREAMBLE):
        for advice in (
            "a report as a document",
            "a deck as slides",
            "a design with 2 to 4 variants (A, B, C)",
            "design_system",
            "html for anything interactive",
            "artifact_guide",
            "read_artifact",
        ):
            assert advice in text, advice


HOSTS = (
    "cdnjs.cloudflare.com",
    "cdn.jsdelivr.net/npm/",
    "unpkg.com",
    "cdn.tailwindcss.com",
    "code.jquery.com",
)


async def test_the_agent_learns_what_a_page_may_do(ctx: AppContext, provider: FakeProvider) -> None:
    _, tools = await chat(ctx, provider)
    content = cast(dict[str, Any], tools["create_artifact"].schema["properties"])["content"]
    updated = cast(dict[str, Any], tools["update_artifact"].schema["properties"])["content"]
    description = str(content["description"])

    assert updated == content
    assert "design: JSON (not HTML)" in description
    for advice in (
        '"intro": "what is being decided, in 2 to 4 sentences"',
        '"label": "A"',
        '"frame": "auto"',
        "layout stack for full screens (the default), grid for many small designs or elements,"
        " tabs when options are big and best compared one at a time, or canvas",
        "label 1 to 3 letters or digits (A, B, C or 1, 2, 3)",
        "description optional Markdown up to 600 characters, the option's idea and trade-off in"
        " one or two sentences",
        "device phone, tablet, desktop or square",
        "frame window for Mac apps, browser for websites (url, up to 200 characters, shows in"
        " its address bar), phone or tablet for mobile bezels, none only if the html draws its"
        " own chrome, or auto",
        "End your chat reply by asking the user to answer with a label.",
        "For live 3D or animated pieces make an html page laid out the same way (an intro, then"
        " labelled items with a title and description), since design screens are static.",
    ):
        assert advice in description, advice
    for text in (description,):
        for host in HOSTS:
            assert host in text
        for rule in (
            "stylesheets and fonts only from Google Fonts",
            "an exact version (react@18.3.1, never react or react@18)",
            "everything else inline or in files",
            "images as data: URIs or files",
            "no fetch or forms",
            "To remember what the user enters, use localStorage as you normally would"
            " (localStorage.getItem/setItem work as usual; Nest keeps it, shared across the"
            " user's devices",
            "window.nest.storage offers the same with get/set and onChange for changes from the"
            " user's other devices",
            "localStorage.getItem/setItem work as usual",
            USAGE_SHAPE,
            ASK_SHAPE,
            "Ask Claude only for small text tasks (at most 20 a day per artifact by default,"
            " short answers, no tools): only when the user does something, never on load or in"
            " a loop, and show the answer as text, not HTML",
            "<input type=file> works",
            "keep a picked file's content in storage",
            "window.nest.saveFile({name, content, encoding, mime}) offers a file to save",
            'Links are plain <a href="https://...">',
            "Nest asks the user and opens them in the browser",
            "#anchors work inside the page",
            "window.nest.openLink(url) does the same from script",
            "CSS variables with a prefers-color-scheme: dark block",
            "an explicit body background",
            "canvas charts (Chart.js) need real colors, read with getComputedStyle",
            "no sideways scroll",
            "a short <title>",
            'Babel standalone from these hosts with <script type="text/babel">',
            "tables, Mermaid diagrams (```mermaid blocks) and code blocks",
        ):
            assert rule in text, rule
        assert "navigation" not in text
    assert f"at most {CONTENT_MAX} bytes" in description
    assert "chart" in tools["create_artifact"].description


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
        (
            {"title": "T", "kind": "pdf", "content": "x"},
            "kind: Input should be 'markdown', 'html', 'slides', 'document', 'design' or",
        ),
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
    assert options.allowed_tools == ALLOWED
    assert isinstance(from_subagent, PermissionResultAllow)


async def test_a_pixie_runs_options_serve_both_servers(
    ctx: AppContext, provider: FakeProvider, tmp_path: Path
) -> None:
    boss = await make_boss(ctx, provider)
    run = run_of(provider, await idle(ctx, boss.chat_id))
    options = await options_of(run, tmp_path)

    config, _ = cli_mcp_config(options, tmp_path / "claude")

    assert list(config["mcpServers"]) == ["pixie", "nest"]
    assert options.allowed_tools == ALLOWED
    assert options.hooks is not None
    own_guard = next(m for m in options.hooks["PreToolUse"] if "mcp__pixie__" in (m.matcher or ""))
    assert "mcp__nest__" not in (own_guard.matcher or "")


DECK = "# One\n---\n# Two\n\n```mermaid\ngraph TD; A-->B\n```\n---\n# Three"
DOCUMENT = "# Plan\n\nIntro.\n\n## Goals\n\nShip it.\n\n## Risks\n\nNone.\n"
DESIGN = json.dumps(
    {
        "screens": [
            {"label": "A", "title": "Start", "device": "phone", "html": "<main>A</main>"},
            {"label": "B", "title": "Start", "device": "phone", "html": "<main>B</main>"},
        ],
        "intro": "A is calm; B is bold.",
    }
)
SYSTEM = json.dumps({"name": "Nest", "colors": [{"name": "accent", "light": "#4C6EF5"}]})


@pytest.mark.parametrize(
    ("kind", "content", "extension"),
    [
        ("slides", DECK, "md"),
        ("document", DOCUMENT, "md"),
        ("design", DESIGN, "json"),
        ("design_system", SYSTEM, "json"),
    ],
)
async def test_the_ready_made_kinds_save_their_data(
    ctx: AppContext, provider: FakeProvider, kind: str, content: str, extension: str
) -> None:
    _, tools = await chat(ctx, provider)

    artifact_id = await create(tools, kind=kind, content=content)
    await tools["update_artifact"].handler({"artifact_id": artifact_id, "content": content})

    detail = await ctx.artifacts.detail(artifact_id)
    assert detail.kind == kind
    assert sorted(p.name for p in folder(ctx, artifact_id).iterdir()) == [
        f"v1.{extension}",
        f"v2.{extension}",
    ]
    assert (folder(ctx, artifact_id) / f"v2.{extension}").read_text(encoding="utf-8") == content
    assert [v.author for v in detail.versions] == ["agent", "agent"]


@pytest.mark.parametrize(
    ("kind", "content", "reason"),
    [
        ("slides", "# One\n---\n\n---\n# Three", "slide 2 is empty"),
        ("design", "{}", "the design is not valid: screens is required"),
        (
            "design_system",
            json.dumps({"name": "N", "colors": [{"name": "c", "light": "red"}]}),
            "colors[0].light must be a hex colour",
        ),
    ],
)
async def test_bad_data_for_a_ready_made_kind_is_refused_with_the_reason(
    ctx: AppContext, provider: FakeProvider, kind: str, content: str, reason: str
) -> None:
    _, tools = await chat(ctx, provider)
    good = {"slides": DECK, "design": DESIGN, "design_system": SYSTEM}[kind]
    artifact_id = await create(tools, kind=kind, content=good)

    on_create = await refused(tools, "create_artifact", title="T", kind=kind, content=content)
    on_update = await refused(tools, "update_artifact", artifact_id=artifact_id, content=content)

    assert reason in on_create
    assert reason in on_update
    assert [a.id for a in await ctx.artifacts.list_artifacts()] == [artifact_id]
    assert (await ctx.artifacts.detail(artifact_id)).version_count == 1


async def test_reading_an_artifact_shows_its_latest_version_and_who_saved_it(
    ctx: AppContext, provider: FakeProvider
) -> None:
    _, tools = await chat(ctx, provider)
    artifact_id = await create(tools, kind="document", content=DOCUMENT, title="Plan")
    agent_read = await tools["read_artifact"].handler({"artifact_id": artifact_id})
    edited = DOCUMENT.replace("Ship it.", "Ship it soon.")
    await ctx.artifacts.edit(artifact_id, edited, 1)

    user_read = await tools["read_artifact"].handler({"artifact_id": artifact_id})

    assert agent_read == (
        f"Artifact {artifact_id}: Plan\nKind: document. Latest version: 1, saved by an agent."
        f"\nStored by its page: nothing.\n\n{DOCUMENT}"
    )
    assert user_read == (
        f"Artifact {artifact_id}: Plan\nKind: document. Latest version: 2, saved by the user"
        f" (edited in Nest's reader).\nStored by its page: nothing.\n\n{edited}"
    )


async def test_reading_a_page_shows_its_files_and_what_it_stored(
    ctx: AppContext, provider: FakeProvider
) -> None:
    _, tools = await chat(ctx, provider)
    files: list[JsonValue] = [
        {"path": "app.js", "content": "go()"},
        {"path": "a.css", "content": ""},
    ]
    artifact_id = await create(tools, kind="html", content="<p>x</p>", title="Tracker", files=files)
    await ctx.artifacts.write_storage(artifact_id, {"day": "Mon", "habits": '["read"]'}, [])

    text = await tools["read_artifact"].handler({"artifact_id": artifact_id})

    assert text == (
        f"Artifact {artifact_id}: Tracker\nKind: html. Latest version: 1, saved by an agent.\n"
        "Files: app.js (4 bytes, text/javascript), a.css (0 bytes, text/css).\n"
        "Stored by its page: 2 keys, 20 bytes, shown after the content.\n\n<p>x</p>\n\n"
        'What the page stored, as JSON:\n{"day": "Mon", "habits": "[\\"read\\"]"}'
    )


async def test_reading_shows_at_most_20_kb_of_stored_data(
    ctx: AppContext, provider: FakeProvider
) -> None:
    _, tools = await chat(ctx, provider)
    artifact_id = await create(tools, kind="html", content="<p>x</p>")
    values = {f"k{i:02}": "v" * 1000 for i in range(30)}
    await ctx.artifacts.write_storage(artifact_id, values, [])
    await ctx.artifacts.write_storage(artifact_id, {"one": "1"}, [])
    big = await create(tools, kind="html", content="<p>y</p>", title="Big")
    await ctx.artifacts.write_storage(big, {"huge": "h" * 30_000}, [])

    text = await tools["read_artifact"].handler({"artifact_id": artifact_id})
    huge = await tools["read_artifact"].handler({"artifact_id": big})

    shown = json.loads(text.split("as JSON:\n", 1)[1].split("\n", 1)[0])
    assert list(shown) == [f"k{i:02}" for i in range(20)]
    assert text.endswith("\n... and 11 more keys")
    assert "Stored by its page: 31 keys," in text
    assert huge.endswith("as JSON:\n{}\n... and 1 more key")


async def test_reading_follows_the_update_rules(ctx: AppContext, provider: FakeProvider) -> None:
    _, tools = await chat(ctx, provider)
    _, other_tools = await chat(ctx, provider, "api")
    theirs = await create(other_tools)

    unknown = await refused(tools, "read_artifact", artifact_id="nope")
    foreign = await refused(tools, "read_artifact", artifact_id=theirs)
    missing = await refused(tools, "read_artifact")

    assert unknown == "unknown artifact 'nope'"
    assert foreign == f"artifact {theirs!r} belongs to another chat; create a new one instead"
    assert missing == "artifact_id: Field required."
    assert tools["read_artifact"].schema["required"] == ["artifact_id"]


async def test_a_pixie_reads_what_its_other_runs_saved(
    ctx: AppContext, provider: FakeProvider
) -> None:
    boss = await make_boss(ctx, provider)
    chat_session = await idle(ctx, boss.chat_id)
    artifact_id = await create(nest_tools(run_of(provider, chat_session)))
    habit_run = chat_session.model_copy(update={"id": "habit-session"})
    again = {t.name: t for t in artifact_tools(ctx.artifacts, habit_run)}

    text = await again["read_artifact"].handler({"artifact_id": artifact_id})

    assert text.endswith(REPORT)


async def test_the_guide_is_nests_design_guidance(ctx: AppContext, provider: FakeProvider) -> None:
    _, tools = await chat(ctx, provider)

    guide = await tools["artifact_guide"].handler({})

    assert tools["artifact_guide"].schema == {"type": "object", "properties": {}}
    assert 150 <= len(guide.splitlines()) <= 260
    assert "\u2014" not in guide
    for topic in (
        "## Layout and spacing",
        "## Type",
        "## Colour",
        "## Motion",
        "prefers-reduced-motion",
        "## Charts",
        "No 3D charts",
        "getComputedStyle",
        "three.js",
        "## Phone width",
        "## Pages that remember",
        "localStorage",
        "localStorage.getItem/setItem work as usual",
        USAGE_SHAPE,
        ASK_SHAPE,
        "window.nest.saveFile",
        "nest.files",
        "## Mockup mode",
        "Start with the intro: what is being decided, in 2 to 4 sentences.",
        "Pick the layout by content: stack for full screens, grid for many small designs or",
        "window for Mac apps, browser for websites",
        "End the chat reply by asking the user to answer with a label.",
        "For live 3D or animated pieces, make an html page laid out the same way",
        "2 to 4",
        "lorem ipsum",
    ):
        assert topic in guide, topic


async def test_a_user_edit_of_a_document_is_a_new_version_by_the_user(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    session, tools = await chat(ctx, provider)
    artifact_id = await create(tools, kind="document", content=DOCUMENT, title="Plan")
    await ctx.artifacts.mark_seen(artifact_id)
    clock.advance(timedelta(minutes=2))

    version = await ctx.artifacts.edit(artifact_id, "# Plan\n\nShorter.\n", 1)

    detail = await ctx.artifacts.detail(artifact_id)
    content = await ctx.artifacts.content(artifact_id, 2)
    assert version == detail.versions[-1]
    assert (version.version, version.title, version.author) == (2, "Plan", "user")
    assert version.created_at == clock.now()
    assert [v.author for v in detail.versions] == ["agent", "user"]
    assert (content.content, content.author) == ("# Plan\n\nShorter.\n", "user")
    assert (await ctx.artifacts.content(artifact_id, 1)).author == "agent"
    assert detail.seen is False
    assert [c["action"] for c in await cards(ctx, session.id)] == ["created", "edited"]
    saved = await published(ctx, types.ARTIFACT_SAVED)
    assert [(s["action"], s["version"], s["unseen"]) for s in saved] == [
        ("created", 1, 1),
        ("edited", 2, 1),
    ]


async def test_only_the_latest_version_of_a_document_is_edited(
    ctx: AppContext, provider: FakeProvider
) -> None:
    _, tools = await chat(ctx, provider)
    document = await create(tools, kind="document", content=DOCUMENT)
    notes = await create(tools, title="Notes")
    await ctx.artifacts.edit(document, DOCUMENT + "\nMore.\n", 1)

    with pytest.raises(StaleVersionError) as stale:
        await ctx.artifacts.edit(document, "# Lost\n", 1)
    with pytest.raises(InvalidArtifactError, match=r"^Only documents can be edited$"):
        await ctx.artifacts.edit(notes, "# Notes\n", 1)
    with pytest.raises(InvalidArtifactError, match="an artifact needs content"):
        await ctx.artifacts.edit(document, " \n", 2)
    with pytest.raises(ArtifactNotFoundError):
        await ctx.artifacts.edit("nope", "# x", 1)

    assert str(stale.value) == (
        "version 1 is not the latest version (2) of this document; reload to edit the latest"
        " version"
    )
    assert (await ctx.artifacts.detail(document)).version_count == 2
    assert (await ctx.artifacts.detail(notes)).version_count == 1


async def test_an_edit_of_an_artifact_without_a_chat_posts_no_card(
    ctx: AppContext, provider: FakeProvider
) -> None:
    _, tools = await chat(ctx, provider)
    artifact_id = await create(tools, kind="document", content=DOCUMENT)
    await ctx.db.execute("UPDATE artifacts SET session_id = NULL WHERE id = ?", (artifact_id,))
    before = len(
        await ctx.db.fetch_all("SELECT id FROM events WHERE type = ?", (types.SESSION_ARTIFACT,))
    )

    await ctx.artifacts.edit(artifact_id, "# Short\n", 1)

    after = len(
        await ctx.db.fetch_all("SELECT id FROM events WHERE type = ?", (types.SESSION_ARTIFACT,))
    )
    assert (before, after) == (1, 1)
    assert [s["action"] for s in await published(ctx, types.ARTIFACT_SAVED)][-1] == "edited"


async def test_a_versions_page_is_built_for_that_version(
    ctx: AppContext, provider: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, tools = await chat(ctx, provider)
    artifact_id = await create(tools, kind="document", content=DOCUMENT, title="Plan")
    await ctx.artifacts.edit(artifact_id, "# Plan\n\nv2\n", 1)
    calls: list[tuple[str, str, str, int]] = []

    def render(kind: str, title: str, content: str, version: int, init: object) -> str:
        assert init == {"storage": {}, "files": []}
        calls.append((kind, title, content, version))
        return f"<page v{version}>"

    monkeypatch.setattr(templates, "render", render)

    second = await ctx.artifacts.content(artifact_id, 2)
    first = await ctx.artifacts.content(artifact_id, 1)

    assert (first.page, second.page) == ("<page v1>", "<page v2>")
    assert calls == [
        ("document", "Plan", "# Plan\n\nv2\n", 2),
        ("document", "Plan", DOCUMENT, 1),
    ]


async def test_reading_says_how_often_the_page_asked_claude_today(
    ctx: AppContext, provider: FakeProvider
) -> None:
    _, tools = await chat(ctx, provider)
    artifact_id = await create(tools, kind="html", content="<p>x</p>", title="Ask")
    quiet = await tools["read_artifact"].handler({"artifact_id": artifact_id})
    await ctx.db.execute(
        "INSERT INTO artifact_asks (artifact_id, at, ok) VALUES (?, ?, 1), (?, ?, 0)",
        (artifact_id, ctx.clock.now().isoformat(), artifact_id, ctx.clock.now().isoformat()),
    )

    text = await tools["read_artifact"].handler({"artifact_id": artifact_id})

    assert "Asks of Claude" not in quiet
    assert "\nAsks of Claude today: 2 of 20.\nStored by its page: nothing." in text
