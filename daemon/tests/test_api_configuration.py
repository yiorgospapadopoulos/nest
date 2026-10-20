"""B97: Settings > Configuration, the page, files, "uses shared" switches and skills.

Every engine folder is in `tmp_path`; Codex is the in-memory app-server answering as Codex
0.163 does, and `claude` is the fake command line.
"""

import json
from pathlib import Path

import pytest

from nestd.configuration.locations import Locations
from tests.api_client import Api
from tests.configuration_api import (
    PLUGINS,
    STATUS,
    engine,
    page,
    servers,
    sign_out_codex,
    skills,
    write_claude_json,
)
from tests.configuration_support import FakeCodexSetup, skill
from tests.git_support import init_repo


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/configuration"),
        ("GET", "/api/configuration/file?path=/x"),
        ("PUT", "/api/configuration/uses-shared"),
        ("POST", "/api/configuration/copy/claude"),
        ("GET", "/api/configuration/codex/plugins"),
        ("GET", "/api/repos/x/configuration"),
    ],
)
async def test_routes_need_a_device(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": ""})

    assert response.status_code == 401


async def test_the_page_with_claude_only(api: Api, where: Locations, tmp_path: Path) -> None:
    await sign_out_codex(api)
    skill(where.shared_skills, "release")
    skill(where.synced_skills, "chrome-browser")
    plugin_folder = tmp_path / "plugins" / "superpowers"
    skill(plugin_folder / "skills", "brainstorming", "Ideas first")
    api.claude.replies[PLUGINS] = [
        json.dumps(
            [
                {"id": "superpowers@market", "enabled": True, "installPath": str(plugin_folder)},
                {"id": "off@market", "enabled": False, "installPath": str(tmp_path / "off")},
            ]
        )
    ]
    where.claude_settings.write_text(
        json.dumps(
            {
                "enabledPlugins": {"superpowers@market": True, "off@market": False},
                "permissions": {"allow": ["Bash(ls)", "Read"], "deny": ["Bash(rm)"]},
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}],
                    "PreToolUse": [{"matcher": "Bash", "hooks": [{}, {}]}, "odd"],
                },
            }
        ),
        encoding="utf-8",
    )
    (where.claude_dir / "agents").mkdir()
    (where.claude_dir / "agents" / "reviewer.md").write_text("x", encoding="utf-8")
    (where.claude_dir / "commands" / "deep").mkdir(parents=True)
    (where.claude_dir / "commands" / "deep" / "ship.md").write_text("x", encoding="utf-8")
    write_claude_json(where, {"ctx": {"type": "http", "url": "https://ctx.example/mcp"}})

    body = await page(api)

    assert body["shared"]["instructions"] == {
        "path": str(where.shared_instructions),
        "exists": False,
        "version": None,
    }
    assert body["shared"]["skills"]["folder"] == str(where.shared_skills)
    listed = skills(body)
    assert listed["yours:release"]["read_only"] is False
    assert listed["yours:release"]["codex_enabled"] is None
    assert listed["synced:chrome-browser"]["read_only"] is True
    # A plugin's skills are Claude's own, shown under the plugin, never in Shared.
    assert list(listed) == ["synced:chrome-browser", "yours:release"]
    assert servers(body)["ctx"] == {
        "name": "ctx",
        "summary": "https://ctx.example/mcp",
        "transport": "http",
        "engines": ["claude"],
        "convertible": True,
        "reason": None,
    }
    assert [section["id"] for section in body["engines"]] == ["claude"]
    claude = engine(body, "claude")
    assert claude["name"] == "Claude"
    assert claude["account"] == "me@example.com · Claude Max"
    assert claude["bundled_version"] == "2.1.286"
    assert claude["standalone"] is None
    assert claude["config_folder"] == str(where.claude_dir)
    assert claude["uses_shared"] == {
        "instructions": {"on": False, "fixed": False},
        "skills": {"on": True, "fixed": True},
        "mcp_servers": {"on": True, "fixed": False},
    }
    assert claude["missing_from_shared"] == {
        "instructions": False,
        "skills": [],
        "mcp_servers": [],
    }
    items = {item["kind"]: item for item in claude["items"]}
    assert items["plugins"]["count"] == 1
    assert items["connectors"]["count"] == 0
    assert items["hooks"]["count"] == 3
    assert items["subagents"] == {
        "kind": "subagents",
        "count": 1,
        "detail": None,
        "path": str(where.claude_dir / "agents"),
        "folder": True,
    }
    assert items["commands"]["count"] == 1
    assert items["permissions"]["count"] == 3
    assert items["permissions"]["detail"] == "2 allow · 1 deny"
    assert items["settings"]["path"] == str(where.claude_settings)


async def test_claude_without_a_readable_setup(api: Api, where: Locations) -> None:
    await sign_out_codex(api)
    api.claude.replies.clear()
    where.claude_settings.write_text("[not json", encoding="utf-8")

    body = await page(api)

    claude = engine(body, "claude")
    assert claude["account"] is None
    assert {item["kind"]: item["count"] for item in claude["items"]}["permissions"] == 0
    where.claude_settings.write_text('{"hooks": [], "enabledPlugins": []}', encoding="utf-8")
    assert engine(await page(api), "claude")["items"][0]["count"] == 0


async def test_claude_signed_out_is_not_shown(api: Api) -> None:
    await sign_out_codex(api)
    api.claude.replies[STATUS] = ['{"loggedIn": false}']

    assert (await page(api))["engines"] == []


async def test_the_page_with_codex(
    api: Api, where: Locations, codex: FakeCodexSetup, tmp_path: Path
) -> None:
    skill(where.shared_skills, "release")
    skill(where.shared_skills, "no-description", description=None)
    skill(where.shared_skills, "switched-off")
    skill(where.codex_skills, "codex-own")
    skill(where.codex_skills, "release")
    agents = tmp_path / "agents-skills"
    skill(agents, "elsewhere")
    codex.roots.append(agents)
    where.codex_skills.mkdir(exist_ok=True)
    where.skills_link.symlink_to(where.shared_skills)
    codex.disabled.add(str(where.skills_link / "switched-off" / "SKILL.md"))
    (where.codex_home / "rules").mkdir()
    (where.codex_home / "rules" / "default.rules").write_text("x", encoding="utf-8")
    write_claude_json(
        where,
        {
            "ctx": {"command": "npx", "args": ["ctx"]},
            "events": {"type": "sse", "url": "https://events/sse"},
            "bad": {"type": "http"},
        },
    )
    codex.servers = {
        "ctx": {"command": "npx", "args": ["ctx"]},
        "docs": {"url": "https://docs/mcp", "bearer_token_env_var": "DOCS"},
        "broken": {"enabled": True},
    }
    standalone = tmp_path / "home" / ".local" / "bin" / "codex"
    standalone.parent.mkdir(parents=True)
    standalone.write_text("#!/bin/sh\necho codex-cli 0.150.0\n", encoding="utf-8")
    standalone.chmod(0o755)

    body = await page(api)

    listed = skills(body)
    assert listed["yours:release"]["codex_enabled"] is True
    assert listed["yours:switched-off"]["codex_enabled"] is False
    assert listed["yours:no-description"]["codex_enabled"] is False
    assert listed["yours:no-description"]["codex_error"] == "missing field `description`"
    assert listed["engine_only:codex-own"]["engine"] == "codex"
    assert listed["engine_only:codex-own"]["read_only"] is False
    assert listed["engine_only:elsewhere"]["read_only"] is True
    shared = servers(body)
    assert list(shared) == ["ctx", "docs", "events"]
    assert shared["ctx"]["engines"] == ["claude", "codex"]
    assert shared["docs"]["summary"] == "https://docs/mcp"
    assert shared["docs"]["engines"] == ["codex"]
    assert shared["events"]["convertible"] is False
    assert shared["events"]["reason"] == "Codex has no SSE servers"
    section = engine(body, "codex")
    assert section["account"] == "me@example.com · ChatGPT Plus"
    assert section["bundled_version"] == "0.163.0"
    assert section["standalone"] == {"path": str(standalone), "version": "0.150.0"}
    assert section["config_folder"] == str(where.codex_home)
    assert section["uses_shared"]["instructions"] == {"on": True, "fixed": True}
    assert section["uses_shared"]["skills"] == {"on": True, "fixed": False}
    assert section["missing_from_shared"] == {
        "instructions": False,
        # `release` is in Shared already; Codex's own copy is skipped, not missing.
        "skills": ["codex-own", "elsewhere"],
        "mcp_servers": ["docs"],
    }
    items = {item["kind"]: item for item in section["items"]}
    assert items["plugins"]["count"] == 1
    assert items["hooks"]["count"] == 1
    assert items["rules"]["count"] == 1
    assert items["settings"]["path"] == str(where.codex_config)


async def test_a_standalone_codex_that_cannot_say_its_version(
    api: Api, codex: FakeCodexSetup, tmp_path: Path
) -> None:
    standalone = tmp_path / "home" / ".local" / "bin" / "codex"
    standalone.parent.mkdir(parents=True)
    for script in ("#!/bin/sh\nexit 3\n", "#!/bin/sh\n"):
        standalone.write_text(script, encoding="utf-8")
        standalone.chmod(0o755)

        section = engine(await page(api), "codex")

        assert section["standalone"] == {"path": str(standalone), "version": None}


async def test_codex_that_cannot_be_asked_shows_an_empty_section(
    api: Api, where: Locations
) -> None:
    api.codex.errors["skills/list"] = (-32000, "broken")
    skill(where.shared_skills, "release")

    body = await page(api)

    assert skills(body)["yours:release"]["codex_enabled"] is None
    assert engine(body, "codex")["missing_from_shared"]["skills"] == []


async def test_claude_and_codex_own_instructions(api: Api, where: Locations) -> None:
    where.claude_md.write_text("# Mine\n\nUse tabs.\n", encoding="utf-8")
    where.shared_instructions.write_text("# Shared\n", encoding="utf-8")

    assert engine(await page(api), "claude")["missing_from_shared"]["instructions"] is True

    where.shared_instructions.write_text("# Mine\n\nUse tabs.\n", encoding="utf-8")
    assert engine(await page(api), "claude")["missing_from_shared"]["instructions"] is False

    where.claude_md.write_text(f"{where.import_line()}\n\n# More\n", encoding="utf-8")
    claude = engine(await page(api), "claude")
    assert claude["missing_from_shared"]["instructions"] is False
    assert claude["uses_shared"]["instructions"]["on"] is True


async def test_files_are_read_and_written_with_versions(api: Api, where: Locations) -> None:
    path = str(where.claude_md)

    missing = await api.http.get("/api/configuration/file", params={"path": path})
    assert missing.json() == {"path": path, "text": "", "version": None}

    created = await api.http.put(
        "/api/configuration/file", json={"path": path, "text": "one\n", "expected_version": None}
    )
    assert created.status_code == 200
    version = created.json()["version"]
    read = await api.http.get("/api/configuration/file", params={"path": path})
    assert read.json() == {"path": path, "text": "one\n", "version": version}

    stale = await api.http.put(
        "/api/configuration/file", json={"path": path, "text": "two\n", "expected_version": None}
    )
    assert stale.status_code == 409
    assert stale.json() == {"detail": f"{path} changed on disk", "current_version": version}

    saved = await api.http.put(
        "/api/configuration/file", json={"path": path, "text": "two\n", "expected_version": version}
    )
    assert saved.status_code == 200
    assert where.claude_md.read_text(encoding="utf-8") == "two\n"
    backups = sorted((api.ctx.paths.data_dir / "config-backups").iterdir())
    mirror = backups[-1] / where.claude_md.relative_to("/")
    assert mirror.read_text(encoding="utf-8") == "one\n"


async def test_files_outside_the_allow_list_are_refused(
    api: Api, where: Locations, tmp_path: Path
) -> None:
    where.codex_config.write_text('model = "gpt-6"\n', encoding="utf-8")
    for path in (str(where.claude_json), str(tmp_path / "x"), "relative.md"):
        read = await api.http.get("/api/configuration/file", params={"path": path})
        assert read.status_code == 403


async def test_codex_config_is_saved_whole_when_it_parses(api: Api, where: Locations) -> None:
    where.codex_config.write_text('model = "gpt-6"\n', encoding="utf-8")
    path = str(where.codex_config)
    read = await api.http.get("/api/configuration/file", params={"path": path})
    version = read.json()["version"]

    broken = await api.http.put(
        "/api/configuration/file",
        json={"path": path, "text": 'model = "gpt-6"\n[oops\n', "expected_version": version},
    )

    assert broken.status_code == 422
    assert "line 2" in broken.json()["detail"]
    assert where.codex_config.read_text(encoding="utf-8") == 'model = "gpt-6"\n'

    saved = await api.http.put(
        "/api/configuration/file",
        json={"path": path, "text": '# mine\nmodel = "gpt-7"\n', "expected_version": version},
    )

    assert saved.status_code == 200
    assert where.codex_config.read_text(encoding="utf-8") == '# mine\nmodel = "gpt-7"\n'
    backups = sorted((api.ctx.paths.data_dir / "config-backups").iterdir())
    mirror = backups[-1] / where.codex_config.relative_to("/")
    assert mirror.read_text(encoding="utf-8") == 'model = "gpt-6"\n'
    stale = await api.http.put(
        "/api/configuration/file", json={"path": path, "text": "", "expected_version": version}
    )
    assert stale.status_code == 409


async def test_a_repos_files_are_allowed_once_registered(api: Api, tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    path = str(repo / "AGENTS.md")
    body = {"path": path, "text": "# Repo\n", "expected_version": None}

    assert (await api.http.put("/api/configuration/file", json=body)).status_code == 403
    await api.http.post("/api/repos", json={"path": str(repo)})
    assert (await api.http.put("/api/configuration/file", json=body)).status_code == 200


async def test_claude_imports_the_shared_instructions(api: Api, where: Locations) -> None:
    where.claude_md.write_text("# Mine\n", encoding="utf-8")
    await api.ctx.codex.status()
    where.shared_instructions.unlink()

    on = await api.http.put(
        "/api/configuration/uses-shared",
        json={"engine": "claude", "item": "instructions", "on": True},
    )

    assert on.status_code == 200
    assert engine(on.json(), "claude")["uses_shared"]["instructions"]["on"] is True
    assert where.claude_md.read_text(encoding="utf-8") == f"{where.import_line()}\n\n# Mine\n"
    assert where.shared_instructions.read_text(encoding="utf-8") == ""
    again = await api.http.put(
        "/api/configuration/uses-shared",
        json={"engine": "claude", "item": "instructions", "on": True},
    )
    assert again.status_code == 200

    off = await api.http.put(
        "/api/configuration/uses-shared",
        json={"engine": "claude", "item": "instructions", "on": False},
    )

    assert engine(off.json(), "claude")["uses_shared"]["instructions"]["on"] is False
    assert where.claude_md.read_text(encoding="utf-8") == "# Mine\n"
    assert where.shared_instructions.exists()


@pytest.mark.parametrize(("engine_id", "item"), [("claude", "skills"), ("codex", "instructions")])
async def test_fixed_switches_cannot_change(api: Api, engine_id: str, item: str) -> None:
    response = await api.http.put(
        "/api/configuration/uses-shared", json={"engine": engine_id, "item": item, "on": False}
    )

    assert response.status_code == 422


async def test_switches_of_an_engine_not_signed_in(api: Api) -> None:
    await sign_out_codex(api)

    response = await api.http.put(
        "/api/configuration/uses-shared", json={"engine": "codex", "item": "skills", "on": True}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Codex is not signed in"


async def test_codex_is_pointed_at_the_shared_skills(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    skill(where.synced_skills, "chrome-browser")
    skill(where.synced_skills, "computer-use")
    skill(where.synced_skills, "pdf")
    skill(where.shared_skills, "release")

    on = await api.http.put(
        "/api/configuration/uses-shared", json={"engine": "codex", "item": "skills", "on": True}
    )

    assert on.status_code == 200
    assert where.skills_link.readlink() == where.shared_skills
    assert sorted(Path(path).parent.name for path in codex.disabled) == [
        "chrome-browser",
        "computer-use",
    ]
    listed = skills(on.json())
    assert listed["synced:chrome-browser"]["codex_enabled"] is False
    assert listed["synced:pdf"]["codex_enabled"] is True
    assert listed["yours:release"]["codex_enabled"] is True
    assert api.ctx.settings.configuration.codex_claude_only_off is True

    # The user switches one back on; sharing off and on again keeps that choice.
    codex.disabled.clear()
    off = await api.http.put(
        "/api/configuration/uses-shared", json={"engine": "codex", "item": "skills", "on": False}
    )
    assert engine(off.json(), "codex")["uses_shared"]["skills"]["on"] is False
    assert not where.skills_link.is_symlink()
    assert (where.shared_skills / "release" / "SKILL.md").is_file()
    await api.http.put(
        "/api/configuration/uses-shared", json={"engine": "codex", "item": "skills", "on": True}
    )
    await api.http.put(
        "/api/configuration/uses-shared", json={"engine": "codex", "item": "skills", "on": True}
    )
    assert codex.disabled == set()


async def test_the_skills_link_name_taken_by_something_else(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    (where.skills_link).mkdir(parents=True)
    body = {"engine": "codex", "item": "skills", "on": True}

    taken = await api.http.put("/api/configuration/uses-shared", json=body)

    assert taken.status_code == 409
    nothing = await api.http.put("/api/configuration/uses-shared", json={**body, "on": False})
    assert nothing.status_code == 200
    assert where.skills_link.is_dir()
    where.skills_link.rmdir()
    other = where.codex_home / "other"
    other.mkdir()
    where.skills_link.symlink_to(other)
    assert (await api.http.put("/api/configuration/uses-shared", json=body)).status_code == 409
    off = await api.http.put("/api/configuration/uses-shared", json={**body, "on": False})
    assert off.status_code == 409
    assert where.skills_link.is_symlink()


async def test_mcp_sharing_is_a_nest_preference(api: Api, codex: FakeCodexSetup) -> None:
    response = await api.http.put(
        "/api/configuration/uses-shared",
        json={"engine": "codex", "item": "mcp_servers", "on": False},
    )

    assert engine(response.json(), "codex")["uses_shared"]["mcp_servers"]["on"] is False
    assert api.ctx.settings.configuration.mcp_shared.codex is False
    assert "codex = false" in api.ctx.paths.settings_file.read_text(encoding="utf-8")


async def test_new_and_removed_skills(api: Api, where: Locations) -> None:
    await sign_out_codex(api)

    created = await api.http.post(
        "/api/configuration/skills", json={"name": "notes", "description": "Takes notes"}
    )

    assert created.status_code == 200
    assert skills(created.json())["yours:notes"]["description"] == "Takes notes"
    exists = await api.http.post("/api/configuration/skills", json={"name": "notes"})
    assert exists.status_code == 409
    bad = await api.http.post("/api/configuration/skills", json={"name": "Not OK"})
    assert bad.status_code == 422

    removed = await api.http.delete("/api/configuration/skills/notes")

    assert removed.status_code == 200
    assert "yours:notes" not in skills(removed.json())
    assert not (where.shared_skills / "notes").exists()
    assert (await api.http.delete("/api/configuration/skills/notes")).status_code == 404


async def test_read_only_skills_are_not_removed(api: Api, where: Locations) -> None:
    await sign_out_codex(api)
    skill(where.synced_skills, "pdf")

    response = await api.http.delete("/api/configuration/skills/pdf")

    assert response.status_code == 403
    assert (where.synced_skills / "pdf").is_dir()


async def test_a_codex_skill_is_made_shared(
    api: Api, where: Locations, codex: FakeCodexSetup, tmp_path: Path
) -> None:
    skill(where.codex_skills, "codex-own")
    outside = tmp_path / "linked-skill"
    skill(tmp_path, "linked-skill")
    (where.codex_skills / "linked").symlink_to(outside)
    agents = tmp_path / "agents"
    skill(agents, "elsewhere")
    codex.roots.append(agents)

    moved = await api.http.post(
        "/api/configuration/skills/codex-own/make-shared", json={"engine": "codex"}
    )

    assert moved.status_code == 200
    assert (where.shared_skills / "codex-own" / "SKILL.md").is_file()
    assert not (where.codex_skills / "codex-own").exists()
    assert where.skills_link.is_symlink()
    assert skills(moved.json())["yours:codex-own"]["codex_enabled"] is True

    linked = await api.http.post("/api/configuration/skills/linked/make-shared", json={})
    assert linked.status_code == 200
    assert (where.shared_skills / "linked").readlink() == outside
    assert not (where.codex_skills / "linked").is_symlink()
    assert (outside / "SKILL.md").is_file()

    refused = await api.http.post("/api/configuration/skills/elsewhere/make-shared", json={})
    assert refused.status_code == 403
    unknown = await api.http.post("/api/configuration/skills/nothing/make-shared", json={})
    assert unknown.status_code == 404
    claude = await api.http.post(
        "/api/configuration/skills/x/make-shared", json={"engine": "claude"}
    )
    assert claude.status_code == 422


async def test_a_relative_link_is_moved_as_an_absolute_one(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    skill(where.codex_home / "kept", "kept-skill")
    where.codex_skills.mkdir()
    (where.codex_skills / "kept-skill").symlink_to(Path("..") / "kept" / "kept-skill")

    response = await api.http.post("/api/configuration/skills/kept-skill/make-shared", json={})

    assert response.status_code == 200
    target = where.codex_home / "kept" / "kept-skill"
    assert (where.shared_skills / "kept-skill").readlink() == target


async def test_making_shared_a_name_shared_already(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    skill(where.codex_skills, "release")
    skill(where.shared_skills, "release")

    response = await api.http.post("/api/configuration/skills/release/make-shared", json={})

    assert response.status_code == 409
    assert (where.codex_skills / "release").is_dir()


async def test_make_shared_needs_codex(api: Api) -> None:
    await sign_out_codex(api)

    response = await api.http.post("/api/configuration/skills/x/make-shared", json={})

    assert response.status_code == 404


async def test_a_skill_is_switched_off_for_codex(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    skill(where.shared_skills, "release")
    skill(where.shared_skills, "no-description", description=None)
    where.codex_skills.mkdir()
    where.skills_link.symlink_to(where.shared_skills)

    off = await api.http.put(
        "/api/configuration/skills/release/engines/codex", json={"enabled": False}
    )

    assert off.status_code == 200
    assert skills(off.json())["yours:release"]["codex_enabled"] is False
    assert codex.disabled == {str(where.skills_link / "release" / "SKILL.md")}
    not_loaded = await api.http.put(
        "/api/configuration/skills/no-description/engines/codex", json={"enabled": True}
    )
    assert not_loaded.status_code == 409
    unknown = await api.http.put(
        "/api/configuration/skills/nothing/engines/codex", json={"enabled": True}
    )
    assert unknown.status_code == 404
    await sign_out_codex(api)
    signed_out = await api.http.put(
        "/api/configuration/skills/release/engines/codex", json={"enabled": True}
    )
    assert signed_out.status_code == 404


async def test_codex_refusing_a_change_is_502(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    skill(where.shared_skills, "release")
    where.codex_skills.mkdir()
    where.skills_link.symlink_to(where.shared_skills)
    api.codex.errors["skills/config/write"] = (-32602, "invalid path")

    response = await api.http.put(
        "/api/configuration/skills/release/engines/codex", json={"enabled": False}
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Codex refused: invalid path"


async def test_codex_enabled_is_unknown_while_codex_does_not_use_the_shared_skills(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    skill(where.shared_skills, "release")
    skill(where.synced_skills, "pdf")

    listed = skills(await page(api))

    assert listed["yours:release"]["codex_enabled"] is None
    assert listed["synced:pdf"]["codex_enabled"] is None


async def test_a_codex_skill_claude_has_from_a_plugin_is_not_missing(
    api: Api, where: Locations, codex: FakeCodexSetup, tmp_path: Path
) -> None:
    plugin_folder = tmp_path / "plugins" / "superpowers"
    skill(plugin_folder / "skills", "brainstorming")
    api.claude.replies[PLUGINS] = [
        json.dumps(
            [{"id": "superpowers@market", "enabled": True, "installPath": str(plugin_folder)}]
        )
    ]
    agents = tmp_path / "agents" / "superpowers"
    skill(agents, "brainstorming")
    skill(where.codex_skills, "codex-own")
    codex.roots.append(agents)

    body = await page(api)

    assert engine(body, "codex")["missing_from_shared"]["skills"] == ["codex-own"]
    assert skills(body)["engine_only:brainstorming"]["engine"] == "codex"
    preview = (await api.http.get("/api/configuration/copy/codex")).json()
    assert preview["skills"] == {
        "add": ["codex-own"],
        "already": [],
        "same_name": [{"name": "brainstorming", "reason": "Claude has it from plugin superpowers"}],
    }


async def test_codex_servers_inside_the_codex_app_stay_with_codex(
    api: Api, where: Locations, codex: FakeCodexSetup
) -> None:
    codex.servers = {
        "computer-use": {"command": "./Codex Computer Use.app/Contents/MacOS/mcp"},
        "tool": {"command": "bin/tool"},
        "npx": {"command": "npx"},
        "abs": {"command": "/usr/local/bin/tool"},
    }

    shared = servers(await page(api))

    assert shared["computer-use"]["convertible"] is False
    assert shared["computer-use"]["reason"] == "Uses a path inside the Codex app"
    assert shared["tool"]["convertible"] is False
    assert shared["npx"]["convertible"] is True
    assert shared["abs"]["convertible"] is True
    preview = (await api.http.get("/api/configuration/copy/codex")).json()
    assert preview["mcp_servers"] == {
        "add": ["abs", "npx"],
        "already": [],
        "not_convertible": [
            {"name": "computer-use", "reason": "Uses a path inside the Codex app"},
            {"name": "tool", "reason": "Uses a path inside the Codex app"},
        ],
    }
