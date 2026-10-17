"""The skills a pixie can be given (D109): standalone skills and every enabled plugin's,
named `<plugin>:<skill>` as Claude Code names them. Every `claude` run is faked."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.gitops.runner import CommandError
from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore

LIST = ("plugin", "list", "--json")


def details(*skills: str) -> str:
    listed = f"  {', '.join(skills)}" if skills else ""
    return (
        "docs\n  Description: Documents.\n\nComponent inventory\n"
        f"  Skills ({len(skills)}){listed}\n  Agents (0)\n  Hooks (0)\n"
    )


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def test_the_route_needs_a_device_token(api: Api) -> None:
    response = await api.http.get("/api/pixies/skills", headers={"Authorization": "Bearer x"})

    assert response.status_code == 401


async def test_standalone_and_enabled_plugin_skills_by_name(api: Api, tmp_path: Path) -> None:
    write(tmp_path / "claude" / "skills" / "notes" / "SKILL.md", "---\ndescription: Notes\n---\n")
    docs = tmp_path / "cache" / "docs"
    write(docs / "skills" / "xlsx" / "SKILL.md", "---\nname: xlsx\ndescription: Sheets\n---\n")
    # In the folder but not part of the plugin: its marketplace lists only some skills.
    write(docs / "skills" / "art" / "SKILL.md", "---\nname: art\ndescription: Art\n---\n")
    write(docs / "commands" / "tidy.md", "---\ndescription: Tidy up\n---\nDo it.")
    write(docs / "commands" / "notes.txt", "not a command")
    plugins = [
        {"id": "docs@market", "enabled": True, "installPath": str(docs)},
        {"id": "bare@market", "enabled": True},
        {"id": "off@market", "enabled": False, "installPath": str(docs)},
    ]
    api.claude.script(*LIST, reply=json.dumps(plugins))
    api.claude.script("plugin", "details", "docs@market", reply=details("xlsx", "tidy"))
    api.claude.script("plugin", "details", "bare@market", reply=details("solo"))

    response = await api.http.get("/api/pixies/skills")

    assert response.status_code == 200
    assert response.json() == [
        {"name": "bare:solo", "description": None, "plugin": "bare"},
        {"name": "docs:tidy", "description": "Tidy up", "plugin": "docs"},
        {"name": "docs:xlsx", "description": "Sheets", "plugin": "docs"},
        {"name": "notes", "description": "Notes", "plugin": None},
    ]
    # A disabled plugin is not asked about.
    asked = api.claude.args_of(api.ctx.claude_code.locations.bundled)
    assert ("plugin", "details", "off@market") not in asked


async def test_a_plugin_whose_details_fail_lists_its_skills_folder(
    api: Api, tmp_path: Path
) -> None:
    folder = tmp_path / "cache" / "kit"
    write(folder / "skills" / "plan" / "SKILL.md", "---\ndescription: Plans\n---\n")
    write(folder / "skills" / "empty" / "README.md", "no skill here")
    api.claude.script(
        *LIST, reply=json.dumps([{"id": "kit@m", "enabled": True, "installPath": str(folder)}])
    )
    api.claude.script(
        "plugin", "details", "kit@m", reply=CommandError(["claude"], 1, "Plugin not found\n")
    )

    body = (await api.http.get("/api/pixies/skills")).json()

    assert body == [{"name": "kit:plan", "description": "Plans", "plugin": "kit"}]


async def test_unreadable_plugin_folders_are_tolerated(api: Api, tmp_path: Path) -> None:
    folder = tmp_path / "cache" / "locked"
    write(folder / "skills" / "x" / "SKILL.md", "---\ndescription: X\n---\n")
    write(folder / "commands" / "y.md", "---\ndescription: Y\n---\n")
    for part in ("skills", "commands"):
        (folder / part).chmod(0)
    try:
        api.claude.script(
            *LIST,
            reply=json.dumps([{"id": "locked@m", "enabled": True, "installPath": str(folder)}]),
        )
        api.claude.script("plugin", "details", "locked@m", reply=details("x", "y"))

        body = (await api.http.get("/api/pixies/skills")).json()
    finally:
        for part in ("skills", "commands"):
            (folder / part).chmod(0o755)

    assert body == [
        {"name": "locked:x", "description": None, "plugin": "locked"},
        {"name": "locked:y", "description": None, "plugin": "locked"},
    ]


async def test_a_failing_plugin_list_is_a_bad_gateway(api: Api) -> None:
    api.claude.script(*LIST, reply=CommandError(["claude"], 1, "broken\n"))

    response = await api.http.get("/api/pixies/skills")

    assert response.status_code == 502
    assert response.json()["detail"] == "broken"
