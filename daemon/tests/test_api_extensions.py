"""Skills and plugins in Settings (D104), through `claude plugin ...`; every run is faked."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from nestd.claude_code.extensions import Extensions, parse_details
from nestd.events import types
from nestd.gitops.runner import CommandError
from tests.api_client import Api, running_api
from tests.fake_claude import install_standalone
from tests.fakes import FakeClock, FakeSecretStore

OFFICIAL = "claude-plugins-official"
LIST = ("plugin", "list", "--json")
AVAILABLE = ("plugin", "list", "--json", "--available")
MARKETPLACES = ("plugin", "marketplace", "list", "--json")
DETAILS = """github
  Description: Official GitHub MCP server.
  Source: github@claude-plugins-official

Component inventory
  Skills (0)
  Agents (2)  reviewer, planner
  Hooks (1)
  MCP servers (1)  github  (tool schemas resolved at runtime; not counted)
  LSP servers (0)

Projected token cost
  Always-on:   ~0 tok   added to every session
"""


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


def cli(api: Api) -> Path:
    return api.ctx.claude_code.locations.bundled


def installed(tmp_path: Path) -> list[dict[str, Any]]:
    folder = tmp_path / "cache" / "github"
    (folder / ".claude-plugin").mkdir(parents=True)
    (folder / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "github", "description": "GitHub tools."}), encoding="utf-8"
    )
    return [
        {
            "id": f"github@{OFFICIAL}",
            "version": "ea10b213686c",
            "scope": "user",
            "enabled": True,
            "installPath": str(folder),
            "installedAt": "2026-07-05T21:21:55.086Z",
            "projectEnabled": False,
        },
        {"id": "local-thing@mine", "scope": "project", "enabled": False},
    ]


def marketplace_list(tmp_path: Path) -> list[dict[str, Any]]:
    return [
        {
            "name": OFFICIAL,
            "source": "github",
            "repo": "anthropics/claude-plugins-official",
            "installLocation": str(tmp_path / "marketplaces" / OFFICIAL),
        },
        {"name": "mine", "source": "directory", "path": "/Users/me/plugins"},
        {"name": "odd", "source": "url", "url": "https://example.com/marketplace.json"},
        {"name": "bare", "source": "settings"},
    ]


def available(tmp_path: Path) -> dict[str, Any]:
    return {
        "installed": installed(tmp_path),
        "available": [
            {
                "pluginId": f"code-review@{OFFICIAL}",
                "name": "code-review",
                "description": "Reviews pull requests.",
                "marketplaceName": OFFICIAL,
                "source": "./plugins/code-review",
                "installCount": 120,
            },
            {
                "pluginId": f"remote@{OFFICIAL}",
                "name": "remote",
                "marketplaceName": OFFICIAL,
                "version": "1.2.0",
                "source": {
                    "source": "git-subdir",
                    "url": "https://github.com/x/plugins.git",
                    "path": "plugins/remote",
                },
            },
            {
                "pluginId": "npm-thing@odd",
                "name": "npm-thing",
                "marketplaceName": "odd",
                "source": {"source": "npm", "package": "@x/thing"},
            },
        ],
    }


async def published(api: Api) -> int:
    rows = await api.ctx.db.fetch_all(
        "SELECT id FROM events WHERE type = ?", (types.EXTENSIONS_UPDATED,)
    )
    return len(rows)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/extensions/plugins"),
        ("GET", "/api/extensions/skills"),
        ("GET", "/api/extensions/marketplaces"),
        ("POST", "/api/extensions/marketplaces"),
        ("DELETE", "/api/extensions/marketplaces/x"),
        ("GET", "/api/extensions/available"),
        ("GET", "/api/extensions/plugins/a@b/details"),
        ("POST", "/api/extensions/plugins/a@b/install"),
        ("POST", "/api/extensions/plugins/a@b/uninstall"),
        ("PUT", "/api/extensions/plugins/a@b/enabled"),
    ],
)
async def test_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_installed_plugins(api: Api, tmp_path: Path) -> None:
    api.claude.script(*LIST, reply=json.dumps(installed(tmp_path)))

    body = (await api.http.get("/api/extensions/plugins")).json()

    assert body == [
        {
            "id": f"github@{OFFICIAL}",
            "name": "github",
            "marketplace": OFFICIAL,
            "version": "ea10b213686c",
            "enabled": True,
            "scope": "user",
            "description": "GitHub tools.",
        },
        {
            "id": "local-thing@mine",
            "name": "local-thing",
            "marketplace": "mine",
            "version": None,
            "enabled": False,
            "scope": "project",
            "description": None,
        },
    ]
    assert api.claude.args_of(cli(api)) == [LIST]


async def test_the_standalone_cli_is_preferred(api: Api) -> None:
    standalone = install_standalone(api.ctx.claude_code.locations)
    api.claude.script(*LIST, reply="[]")

    assert (await api.http.get("/api/extensions/plugins")).json() == []
    assert api.claude.args_of(standalone) == [LIST]


@pytest.mark.parametrize("reply", ["{}", "nope", '[{"id": 3}]'])
async def test_output_the_daemon_cannot_read_is_a_bad_gateway(api: Api, reply: str) -> None:
    api.claude.script(*LIST, reply=reply)

    response = await api.http.get("/api/extensions/plugins")

    assert response.status_code == 502
    assert "unexpected output" in response.json()["detail"]


async def test_standalone_skills_from_their_front_matter(api: Api, tmp_path: Path) -> None:
    skills = tmp_path / "claude" / "skills"
    for name, text in {
        "release": '---\nname: release-notes\ntags:\ndescription: "Write release notes"\n---\nBody',
        "plain": "No front matter here.",
        "unclosed": "---\nname: x\n",
    }.items():
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(text, encoding="utf-8")
    (skills / "empty").mkdir()
    (skills / "loose.md").write_text("x", encoding="utf-8")

    body = (await api.http.get("/api/extensions/skills")).json()

    assert body == [
        {"name": "plain", "description": None, "path": str(skills / "plain")},
        {
            "name": "release-notes",
            "description": "Write release notes",
            "path": str(skills / "release"),
        },
        {"name": "unclosed", "description": None, "path": str(skills / "unclosed")},
    ]


async def test_no_skills_folder(api: Api) -> None:
    assert (await api.http.get("/api/extensions/skills")).json() == []


async def test_marketplaces(api: Api, tmp_path: Path) -> None:
    api.claude.script(*MARKETPLACES, reply=json.dumps(marketplace_list(tmp_path)))

    body = (await api.http.get("/api/extensions/marketplaces")).json()

    assert body == [
        {"name": OFFICIAL, "kind": "github", "source": "anthropics/claude-plugins-official"},
        {"name": "mine", "kind": "directory", "source": "/Users/me/plugins"},
        {"name": "odd", "kind": "url", "source": "https://example.com/marketplace.json"},
        {"name": "bare", "kind": "settings", "source": None},
    ]


async def test_adding_and_removing_a_marketplace(api: Api) -> None:
    api.claude.script("plugin", "marketplace", "add", "--", "me/plugins", reply="Added\n")
    api.claude.script("plugin", "marketplace", "remove", "mine", reply="Removed\n")

    added = await api.http.post("/api/extensions/marketplaces", json={"source": "me/plugins"})
    removed = await api.http.delete("/api/extensions/marketplaces/mine")

    assert (added.status_code, removed.status_code) == (204, 204)
    assert await published(api) == 2


@pytest.mark.parametrize("source", ["", "  ", "-rf"])
async def test_a_bad_marketplace_source_is_refused(api: Api, source: str) -> None:
    response = await api.http.post("/api/extensions/marketplaces", json={"source": source})

    assert response.status_code == 422
    assert api.claude.calls == []


async def test_cli_errors_come_back_with_their_message(api: Api) -> None:
    api.claude.script(
        "plugin",
        "marketplace",
        "remove",
        "nope",
        reply=CommandError(["claude"], 1, "Marketplace 'nope' not found\n"),
    )

    response = await api.http.delete("/api/extensions/marketplaces/nope")

    assert response.status_code == 502
    assert response.json()["detail"] == "Marketplace 'nope' not found"
    assert await published(api) == 0


async def test_available_plugins_include_the_installed_ones(api: Api, tmp_path: Path) -> None:
    api.claude.script(*AVAILABLE, reply=json.dumps(available(tmp_path)))

    body = (await api.http.get("/api/extensions/available")).json()

    assert [(p["id"], p["installed"]) for p in body] == [
        (f"code-review@{OFFICIAL}", False),
        (f"github@{OFFICIAL}", True),
        ("local-thing@mine", True),
        ("npm-thing@odd", False),
        (f"remote@{OFFICIAL}", False),
    ]
    review = body[0]
    assert review == {
        "id": f"code-review@{OFFICIAL}",
        "name": "code-review",
        "marketplace": OFFICIAL,
        "description": "Reviews pull requests.",
        "version": None,
        "source": "./plugins/code-review",
        "install_count": 120,
        "installed": False,
    }
    assert body[1]["description"] == "GitHub tools."
    assert body[1]["source"] == OFFICIAL
    assert body[3]["source"] == "@x/thing"
    assert (body[4]["source"], body[4]["version"]) == (
        "https://github.com/x/plugins.git plugins/remote",
        "1.2.0",
    )


async def test_details_of_an_installed_plugin(api: Api, tmp_path: Path) -> None:
    api.claude.script(*AVAILABLE, reply=json.dumps(available(tmp_path)))
    api.claude.script("plugin", "details", f"github@{OFFICIAL}", reply=DETAILS)

    body = (await api.http.get(f"/api/extensions/plugins/github@{OFFICIAL}/details")).json()

    assert body == {
        "id": f"github@{OFFICIAL}",
        "name": "github",
        "marketplace": OFFICIAL,
        "description": "Official GitHub MCP server.",
        "source": OFFICIAL,
        "installed": True,
        "components": {
            "skills": {"count": 0, "names": []},
            "agents": {"count": 2, "names": ["reviewer", "planner"]},
            "hooks": {"count": 1, "names": []},
            "mcp_servers": {"count": 1, "names": ["github"]},
            "lsp_servers": {"count": 0, "names": []},
        },
    }


async def test_details_of_a_plugin_in_a_marketplace_checkout(api: Api, tmp_path: Path) -> None:
    api.claude.script(*AVAILABLE, reply=json.dumps(available(tmp_path)))
    api.claude.script(*MARKETPLACES, reply=json.dumps(marketplace_list(tmp_path)))
    folder = tmp_path / "marketplaces" / OFFICIAL / "plugins" / "code-review"
    folder.mkdir(parents=True)
    api.claude.script(
        "--plugin-dir", str(folder), "plugin", "details", "code-review", reply=DETAILS
    )

    body = (await api.http.get(f"/api/extensions/plugins/code-review@{OFFICIAL}/details")).json()

    assert body["installed"] is False
    assert body["description"] == "Reviews pull requests."
    assert body["components"]["agents"]["names"] == ["reviewer", "planner"]


@pytest.mark.parametrize("plugin", [f"remote@{OFFICIAL}", "npm-thing@odd"])
async def test_details_of_a_remote_plugin_have_no_components(
    api: Api, tmp_path: Path, plugin: str
) -> None:
    api.claude.script(*AVAILABLE, reply=json.dumps(available(tmp_path)))
    api.claude.script(*MARKETPLACES, reply=json.dumps(marketplace_list(tmp_path)))

    body = (await api.http.get(f"/api/extensions/plugins/{plugin}/details")).json()

    assert body["components"] is None


@pytest.mark.parametrize("marketplaces", [slice(1, None), slice(None)])
async def test_details_when_the_checkout_is_missing(
    api: Api, tmp_path: Path, marketplaces: slice
) -> None:
    api.claude.script(*AVAILABLE, reply=json.dumps(available(tmp_path)))
    api.claude.script(*MARKETPLACES, reply=json.dumps(marketplace_list(tmp_path)[marketplaces]))

    body = (await api.http.get(f"/api/extensions/plugins/code-review@{OFFICIAL}/details")).json()

    assert body["components"] is None


async def test_details_of_an_unknown_plugin(api: Api, tmp_path: Path) -> None:
    api.claude.script(*AVAILABLE, reply=json.dumps(available(tmp_path)))

    response = await api.http.get(f"/api/extensions/plugins/nope@{OFFICIAL}/details")

    assert response.status_code == 404


def test_details_text_without_an_inventory() -> None:
    description, components = parse_details("name\n  Description: Hi\n")

    assert description == "Hi"
    assert {key: value.model_dump() for key, value in components.items()} == {
        "skills": {"count": 0, "names": []},
        "agents": {"count": 0, "names": []},
        "hooks": {"count": 0, "names": []},
        "mcp_servers": {"count": 0, "names": []},
        "lsp_servers": {"count": 0, "names": []},
    }
    assert parse_details("name\n")[0] is None


async def test_install_uninstall_enable_and_disable(api: Api) -> None:
    plugin = f"github@{OFFICIAL}"
    api.claude.script("plugin", "install", plugin, reply="Installed\n")
    api.claude.script("plugin", "uninstall", plugin, reply="Uninstalled\n")
    api.claude.script("plugin", "enable", plugin, reply="Enabled\n")
    api.claude.script("plugin", "disable", plugin, reply="Disabled\n")

    responses = [
        await api.http.post(f"/api/extensions/plugins/{plugin}/install"),
        await api.http.put(f"/api/extensions/plugins/{plugin}/enabled", json={"enabled": False}),
        await api.http.put(f"/api/extensions/plugins/{plugin}/enabled", json={"enabled": True}),
        await api.http.post(f"/api/extensions/plugins/{plugin}/uninstall"),
    ]

    assert [r.status_code for r in responses] == [204, 204, 204, 204]
    assert [call[1] for call in api.claude.args_of(cli(api))] == [
        "install",
        "disable",
        "enable",
        "uninstall",
    ]
    assert await published(api) == 4


@pytest.mark.parametrize("plugin", ["github", "-x@y", "a@-b", "a@b c"])
async def test_plugin_ids_are_checked(api: Api, plugin: str) -> None:
    response = await api.http.post(f"/api/extensions/plugins/{plugin}/install")

    assert response.status_code == 422
    assert api.claude.calls == []


async def test_a_bad_marketplace_name_is_refused(api: Api) -> None:
    response = await api.http.delete("/api/extensions/marketplaces/-x")

    assert response.status_code == 422


@pytest.mark.parametrize("manifest", ["not json", '{"description": 3}', None])
async def test_a_plugin_without_a_readable_manifest_has_no_description(
    api: Api, tmp_path: Path, manifest: str | None
) -> None:
    folder = tmp_path / "plugin"
    if manifest is not None:
        (folder / ".claude-plugin").mkdir(parents=True)
        (folder / ".claude-plugin" / "plugin.json").write_text(manifest, encoding="utf-8")
    plugin = {"id": "x@y", "installPath": str(folder)}
    api.claude.script(*LIST, reply=json.dumps([plugin]))

    [body] = (await api.http.get("/api/extensions/plugins")).json()

    assert body["description"] is None


async def test_no_claude_folder_lists_no_skills(api: Api) -> None:
    extensions = Extensions(api.ctx.claude_code, api.ctx.bus, None)

    assert await extensions.skills() == []
