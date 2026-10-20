"""B97: shared MCP servers, copying an engine's setup to Shared and undoing it, Codex's
plugins and marketplaces, a project's own setup, and opening files in other apps.
"""

from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from nestd.configuration.locations import Locations
from tests.api_client import Api, running_api
from tests.configuration_api import (
    claude_json,
    engine,
    page,
    servers,
    sign_out_codex,
    skills,
    write_claude_json,
)
from tests.configuration_support import FakeCodexSetup, skill
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo

STDIO = {"transport": "stdio", "command": "npx", "args": ["-y", "ctx"], "env": {"A": "1"}}


async def test_a_server_goes_to_every_sharing_engine(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    write_claude_json(where, {}, oauthAccount={"emailAddress": "me@example.com"})

    response = await api.http.put("/api/configuration/mcp-servers/ctx", json=STDIO)

    assert response.status_code == 200
    assert servers(response.json())["ctx"]["engines"] == ["claude", "codex"]
    data = claude_json(where)
    assert list(data) == ["numStartups", "mcpServers", "oauthAccount"]
    assert data["mcpServers"]["ctx"] == {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "ctx"],
        "env": {"A": "1"},
    }
    assert codex.servers["ctx"] == {"command": "npx", "args": ["-y", "ctx"], "env": {"A": "1"}}
    assert codex.version == 2

    shown = await api.http.get("/api/configuration/mcp-servers/ctx")
    assert shown.json() == {**STDIO, "url": None, "headers": {}}

    removed = await api.http.delete("/api/configuration/mcp-servers/ctx")

    assert removed.status_code == 200
    assert "ctx" not in servers(removed.json())
    assert claude_json(where)["mcpServers"] == {}
    assert codex.servers == {}
    assert (await api.http.delete("/api/configuration/mcp-servers/ctx")).status_code == 404
    assert (await api.http.get("/api/configuration/mcp-servers/ctx")).status_code == 404


async def test_a_server_codex_cannot_take_stays_with_claude(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    sse = {"transport": "sse", "url": "https://events/sse"}

    response = await api.http.put("/api/configuration/mcp-servers/events", json=sse)

    shared = servers(response.json())["events"]
    assert shared["engines"] == ["claude"]
    assert shared["convertible"] is False
    assert codex.servers == {}


async def test_an_engine_not_sharing_is_left_alone(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    await api.http.put(
        "/api/configuration/uses-shared",
        json={"engine": "codex", "item": "mcp_servers", "on": False},
    )

    await api.http.put("/api/configuration/mcp-servers/ctx", json=STDIO)

    assert codex.servers == {}
    assert "ctx" in claude_json(where)["mcpServers"]
    await api.http.put(
        "/api/configuration/uses-shared",
        json={"engine": "claude", "item": "mcp_servers", "on": False},
    )
    nowhere = await api.http.put("/api/configuration/mcp-servers/ctx", json=STDIO)
    assert nowhere.status_code == 422
    codex.servers["docs"] = {"url": "https://docs/mcp"}
    body = await page(api)
    assert body["shared"]["mcp_servers"] == []
    # No other engine shares MCP servers, so a copy would add them nowhere.
    assert engine(body, "codex")["missing_from_shared"]["mcp_servers"] == []
    assert engine(body, "claude")["missing_from_shared"]["mcp_servers"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"transport": "stdio"},
        {"transport": "http"},
        {"transport": "ws", "url": "x"},
        {**STDIO, "extra": 1},
    ],
)
async def test_invalid_servers_are_refused(api: Api, body: dict[str, Any]) -> None:
    response = await api.http.put("/api/configuration/mcp-servers/ctx", json=body)

    assert response.status_code == 422


async def test_server_names_are_checked(api: Api) -> None:
    response = await api.http.put("/api/configuration/mcp-servers/a.b", json=STDIO)

    assert response.status_code == 422


async def test_codex_changing_its_config_meanwhile_is_502(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    api.codex.errors["config/batchWrite"] = (-32000, "config version mismatch")

    response = await api.http.put("/api/configuration/mcp-servers/ctx", json=STDIO)

    assert response.status_code == 502
    assert response.json()["detail"] == "Codex refused: config version mismatch"


async def test_copying_claudes_setup_and_undoing_it(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    where.claude_md.write_text("# Claude's own\n", encoding="utf-8")
    where.shared_instructions.write_text("# Old shared\n", encoding="utf-8")
    skill(where.shared_skills, "release")
    write_claude_json(
        where,
        {
            "ctx": {"command": "npx"},
            "docs": {"type": "http", "url": "https://docs/mcp"},
            "events": {"type": "sse", "url": "https://events/sse"},
        },
    )
    codex.servers = {"docs": {"url": "https://docs/mcp"}}

    preview = await api.http.get("/api/configuration/copy/claude")

    assert preview.json() == {
        "instructions": {
            "replace": True,
            "engine_path": str(where.claude_md),
            "shared_path": str(where.shared_instructions),
        },
        "skills": {"add": [], "already": ["release"], "same_name": []},
        "mcp_servers": {
            "add": ["ctx"],
            "already": ["docs"],
            "not_convertible": [{"name": "events", "reason": "Codex has no SSE servers"}],
        },
        "stays": [
            "plugins themselves",
            "claude.ai connectors",
            "hooks",
            "subagents",
            "slash commands",
            "permission rules",
        ],
    }

    copied = await api.http.post("/api/configuration/copy/claude", json={"instructions": True})

    assert copied.status_code == 200
    result = copied.json()
    assert (
        result["summary"]
        == "Copied to Shared: instructions replaced (backup kept), 1 MCP server added."
    )
    assert where.shared_instructions.read_text(encoding="utf-8") == "# Claude's own\n"
    assert where.claude_md.read_text(encoding="utf-8") == f"{where.import_line()}\n"
    assert codex.servers["ctx"] == {"command": "npx"}
    claude = engine(result["page"], "claude")
    assert claude["missing_from_shared"]["instructions"] is False

    undone = await api.http.post(f"/api/configuration/copy/undo/{result['undo_id']}")

    assert undone.status_code == 200
    assert where.shared_instructions.read_text(encoding="utf-8") == "# Old shared\n"
    assert where.claude_md.read_text(encoding="utf-8") == "# Claude's own\n"
    assert "ctx" not in codex.servers
    assert "ctx" in claude_json(where)["mcpServers"]
    twice = await api.http.post(f"/api/configuration/copy/undo/{result['undo_id']}")
    assert twice.status_code == 409


async def test_copying_but_keeping_the_shared_instructions(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    where.claude_md.write_text("# Claude's own\n", encoding="utf-8")

    copied = await api.http.post("/api/configuration/copy/claude", json={"instructions": False})

    assert copied.json()["summary"] == "Nothing to copy: Shared has all of it already."
    assert where.claude_md.read_text(encoding="utf-8") == "# Claude's own\n"
    assert where.shared_instructions.read_text(encoding="utf-8") == ""


async def test_undo_refuses_after_a_later_edit(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    where.claude_md.write_text("# Claude's own\n", encoding="utf-8")
    copied = await api.http.post("/api/configuration/copy/claude", json={"instructions": True})
    where.shared_instructions.write_text("# Edited after\n", encoding="utf-8")

    undone = await api.http.post(f"/api/configuration/copy/undo/{copied.json()['undo_id']}")

    assert undone.status_code == 409
    assert "AGENTS.md changed since the copy" in undone.json()["detail"]
    assert where.shared_instructions.read_text(encoding="utf-8") == "# Edited after\n"
    assert (await api.http.post("/api/configuration/copy/undo/nothing")).status_code == 404


async def test_copying_codexs_setup_and_undoing_it(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    skill(where.codex_skills, "codex-own")
    skill(where.codex_skills, "release")
    skill(where.shared_skills, "release")
    write_claude_json(where, {"ctx": {"command": "npx"}})
    codex.servers = {
        "ctx": {"command": "npx"},
        "docs": {"url": "https://docs/mcp", "bearer_token_env_var": "DOCS"},
    }

    preview = (await api.http.get("/api/configuration/copy/codex")).json()

    assert preview["instructions"] is None
    assert preview["skills"] == {
        "add": ["codex-own"],
        "already": [],
        "same_name": [{"name": "release", "reason": "Shared has a skill with this name"}],
    }
    assert preview["mcp_servers"] == {"add": ["docs"], "already": ["ctx"], "not_convertible": []}
    assert preview["stays"][-1] == "other config.toml settings"

    copied = await api.http.post("/api/configuration/copy/codex", json={"instructions": True})

    result = copied.json()
    assert result["summary"] == "Copied to Shared: 1 skill and 1 MCP server added."
    assert (where.shared_skills / "codex-own" / "SKILL.md").is_file()
    assert not (where.codex_skills / "codex-own").exists()
    assert where.skills_link.is_symlink()
    assert claude_json(where)["mcpServers"]["docs"] == {
        "type": "http",
        "url": "https://docs/mcp",
        "headers": {"Authorization": "Bearer ${DOCS}"},
    }
    again = (await api.http.get("/api/configuration/copy/codex")).json()
    assert again["skills"]["already"] == ["codex-own", "release"]

    await api.http.post(f"/api/configuration/copy/undo/{result['undo_id']}")

    assert (where.codex_skills / "codex-own" / "SKILL.md").is_file()
    assert not (where.shared_skills / "codex-own").exists()
    assert not where.skills_link.is_symlink()
    assert "docs" not in claude_json(where)["mcpServers"]


async def test_copy_needs_the_engine_signed_in(api: Api) -> None:
    await sign_out_codex(api)

    assert (await api.http.get("/api/configuration/copy/codex")).status_code == 404
    copied = await api.http.post("/api/configuration/copy/codex", json={"instructions": True})
    assert copied.status_code == 404


async def test_copy_with_nothing_else_sharing(api: Api, where: Locations) -> None:
    await sign_out_codex(api)
    write_claude_json(where, {"events": {"type": "sse", "url": "https://events/sse"}})

    preview = (await api.http.get("/api/configuration/copy/claude")).json()

    assert preview["mcp_servers"] == {"add": [], "already": ["events"], "not_convertible": []}


async def test_codex_plugins_and_marketplaces(api: Api, codex: FakeCodexSetup) -> None:
    api.codex.answers["plugin/install"] = {"appsNeedingAuth": [], "authPolicy": "ON_USE"}
    api.codex.answers["plugin/uninstall"] = {}
    api.codex.answers["marketplace/add"] = {"alreadyAdded": False}
    api.codex.answers["marketplace/remove"] = {"marketplaceName": "x"}

    listed = (await api.http.get("/api/configuration/codex/plugins")).json()

    assert [plugin["id"] for plugin in listed["plugins"]] == [
        "figma@openai-curated",
        "linear@openai-curated",
    ]
    assert listed["plugins"][0] == {
        "id": "figma@openai-curated",
        "name": "figma",
        "marketplace": "openai-curated",
        "description": "Design files",
        "version": "1.0.0",
        "installed": True,
        "enabled": True,
    }
    assert listed["marketplaces"] == [
        {"name": "openai-curated", "path": "/codex/marketplaces/curated"}
    ]
    found = await api.http.get("/api/configuration/codex/plugins", params={"query": "ISSUES"})
    assert [plugin["name"] for plugin in found.json()["plugins"]] == ["linear"]

    installed = await api.http.post(
        "/api/configuration/codex/plugins/linear@openai-curated/install"
    )
    assert installed.status_code == 200
    assert api.codex.requests("plugin/install") == [
        {"pluginName": "linear", "marketplacePath": "/codex/marketplaces/curated"}
    ]
    unknown = await api.http.post("/api/configuration/codex/plugins/nope@x/install")
    assert unknown.status_code == 404
    removed = await api.http.post("/api/configuration/codex/plugins/figma@openai-curated/uninstall")
    assert removed.status_code == 200
    assert api.codex.requests("plugin/uninstall") == [{"pluginId": "figma@openai-curated"}]

    marketplaces = await api.http.get("/api/configuration/codex/marketplaces")
    assert marketplaces.json()[0]["name"] == "openai-curated"
    added = await api.http.post(
        "/api/configuration/codex/marketplaces", json={"source": "owner/repo"}
    )
    assert added.status_code == 200
    assert api.codex.requests("marketplace/add") == [{"source": "owner/repo"}]
    option = await api.http.post("/api/configuration/codex/marketplaces", json={"source": "-x"})
    assert option.status_code == 422
    dropped = await api.http.delete("/api/configuration/codex/marketplaces/openai-curated")
    assert dropped.status_code == 200
    assert api.codex.requests("marketplace/remove") == [{"marketplaceName": "openai-curated"}]


async def test_codex_that_cannot_start_is_502(api: Api) -> None:
    api.codex.spawn_error = OSError("no binary")

    response = await api.http.get("/api/configuration/codex/plugins")

    assert response.status_code == 502
    assert response.json()["detail"] == "Codex could not be asked (OSError)"


async def test_a_projects_own_setup(api: Api, tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    await api.http.post("/api/repos", json={"path": str(repo)})
    (repo / "CLAUDE.md").write_text("# Repo\n", encoding="utf-8")
    skill(repo / ".claude" / "skills", "deploy")

    shown = (await api.http.get("/api/repos/repo/configuration")).json()

    assert shown["instructions"] == [
        {"path": str(repo / "AGENTS.md"), "exists": False},
        {"path": str(repo / "CLAUDE.md"), "exists": True},
    ]
    assert [(s["name"], s["source"]) for s in shown["skills"]] == [("deploy", "project")]
    assert shown["mcp_servers"] == []

    put = await api.http.put("/api/repos/repo/configuration/mcp-servers/ctx", json=STDIO)
    assert put.json()["mcp_servers"] == [
        {"name": "ctx", "summary": "npx -y ctx", "transport": "stdio"}
    ]
    assert (repo / ".mcp.json").is_file()
    created = await api.http.post(
        "/api/repos/repo/configuration/skills", json={"name": "lint", "description": "Lints"}
    )
    assert [s["name"] for s in created.json()["skills"]] == ["deploy", "lint"]
    bad = await api.http.post("/api/repos/repo/configuration/skills", json={"name": "Bad!"})
    assert bad.status_code == 422
    deleted = await api.http.delete("/api/repos/repo/configuration/mcp-servers/ctx")
    assert deleted.json()["mcp_servers"] == []
    missing = await api.http.delete("/api/repos/repo/configuration/mcp-servers/ctx")
    assert missing.status_code == 404
    assert (await api.http.get("/api/repos/nothing/configuration")).status_code == 404


async def test_without_engine_folders_there_is_nothing_to_configure(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    async with running_api(tmp_path, clock, secrets) as api:
        response = await api.http.get("/api/configuration")

    assert response.status_code == 404


async def test_signing_in_prepares_the_engines_files(api: Api, where: Locations) -> None:
    await api.ctx.codex.status(refresh=True)

    assert where.shared_instructions.read_text(encoding="utf-8") == ""
    where.shared_instructions.write_text("# Mine\n", encoding="utf-8")
    await api.ctx.codex.status(refresh=True)
    assert where.shared_instructions.read_text(encoding="utf-8") == "# Mine\n"


async def test_the_page_lists_skills_of_both_engines(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    skill(where.shared_skills, "release")
    await sign_out_codex(api)

    assert skills(await page(api))["yours:release"]["codex_enabled"] is None


async def test_a_codex_server_in_claudes_shape(api: Api, codex: FakeCodexSetup) -> None:
    api.claude.replies.clear()
    api.claude.script("auth", "status", "--json", reply='{"loggedIn": false}')
    codex.servers = {"docs": {"url": "https://docs/mcp", "bearer_token_env_var": "DOCS"}}

    response = await api.http.get("/api/configuration/mcp-servers/docs")

    assert response.json() == {
        "transport": "http",
        "command": None,
        "args": [],
        "env": {},
        "url": "https://docs/mcp",
        "headers": {"Authorization": "Bearer ${DOCS}"},
    }


async def test_engine_files_that_cannot_be_made_are_logged(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, caplog: pytest.LogCaptureFixture
) -> None:
    taken = tmp_path / "codex-is-a-file"
    taken.write_text("x", encoding="utf-8")

    async with running_api(tmp_path, clock, secrets, codex_home=taken) as api:
        status = await api.ctx.codex.status(refresh=True)

    assert status.signed_in is True
    assert "could not prepare codex's files" in caplog.text


async def test_editing_a_server_keeps_codexs_own_keys(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    codex.servers = {
        "ctx": {
            "command": "old",
            "args": ["x"],
            "env": {"OLD": "1"},
            "startup_timeout_sec": 30,
            "tool_timeout_sec": 60,
            "enabled": False,
            "required": True,
            "enabled_tools": ["search"],
            "env_vars": ["HOME"],
            "cwd": "/work",
        }
    }

    await api.http.put(
        "/api/configuration/mcp-servers/ctx", json={"transport": "stdio", "command": "npx"}
    )

    assert codex.servers["ctx"] == {
        "startup_timeout_sec": 30,
        "tool_timeout_sec": 60,
        "enabled": False,
        "required": True,
        "enabled_tools": ["search"],
        "env_vars": ["HOME"],
        "cwd": "/work",
        "command": "npx",
    }

    await api.http.put(
        "/api/configuration/mcp-servers/ctx",
        json={"transport": "http", "url": "https://a", "headers": {"X": "1"}},
    )

    assert codex.servers["ctx"] == {
        "startup_timeout_sec": 30,
        "tool_timeout_sec": 60,
        "enabled": False,
        "required": True,
        "enabled_tools": ["search"],
        "env_vars": ["HOME"],
        "cwd": "/work",
        "url": "https://a",
        "http_headers": {"X": "1"},
    }

    await api.http.delete("/api/configuration/mcp-servers/ctx")

    assert codex.servers == {}


@pytest.mark.parametrize(
    ("message", "data"),
    [
        ("write failed", {"configWriteErrorCode": "configVersionConflict"}),
        ("configVersionConflict: the file changed", None),
    ],
)
async def test_codex_config_changed_meanwhile_is_a_conflict(
    api: Api, codex: FakeCodexSetup, message: str, data: JsonValue
) -> None:
    api.codex.errors["config/batchWrite"] = (-32600, message)
    if data is not None:
        api.codex.error_data["config/batchWrite"] = data

    response = await api.http.put("/api/configuration/mcp-servers/ctx", json=STDIO)

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Codex's config.toml changed meanwhile; try again",
        "current_version": None,
    }


async def test_missing_servers_are_what_a_copy_would_add(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    write_claude_json(
        where,
        {"ctx": {"command": "npx"}, "events": {"type": "sse", "url": "https://events/sse"}},
    )
    codex.servers = {"ctx": {"command": "npx"}, "node_repl": {"command": "node"}}

    body = await page(api)

    for engine_id in ("claude", "codex"):
        preview = (await api.http.get(f"/api/configuration/copy/{engine_id}")).json()
        missing = engine(body, engine_id)["missing_from_shared"]["mcp_servers"]
        assert missing == preview["mcp_servers"]["add"]
    assert engine(body, "codex")["missing_from_shared"]["mcp_servers"] == ["node_repl"]
    assert engine(body, "claude")["missing_from_shared"]["mcp_servers"] == []
