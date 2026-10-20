"""A daemon with Claude and Codex signed in, for the configuration API tests (B97)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from nestd.configuration.locations import Locations
from tests.api_client import Api, running_api
from tests.codex_support import SIGNED_OUT
from tests.configuration_support import FakeCodexSetup, locations
from tests.fakes import FakeClock, FakeSecretStore

STATUS = ("auth", "status", "--json")
PLUGINS = ("plugin", "list", "--json")
SIGNED_IN_CLAUDE = json.dumps(
    {"loggedIn": True, "email": "me@example.com", "subscriptionType": "max"}
)


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets, codex_home=tmp_path / "codex") as running:
        running.claude.script(*STATUS, reply=SIGNED_IN_CLAUDE)
        running.claude.script(*PLUGINS, reply="[]")
        yield running


@pytest.fixture
def where(tmp_path: Path) -> Locations:
    return locations(tmp_path)


@pytest.fixture
def codex(api: Api, where: Locations) -> FakeCodexSetup:
    return FakeCodexSetup(api.codex, where)


async def sign_out_codex(api: Api) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT
    await api.ctx.codex.status(refresh=True)


async def page(api: Api) -> dict[str, Any]:
    response = await api.http.get("/api/configuration")
    assert response.status_code == 200, response.text
    return response.json()


def engine(body: dict[str, Any], engine_id: str) -> dict[str, Any]:
    return next(section for section in body["engines"] if section["id"] == engine_id)


def skills(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f"{s['source']}:{s['name']}": s for s in body["shared"]["skills"]["items"]}


def servers(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {server["name"]: server for server in body["shared"]["mcp_servers"]}


def claude_json(where: Locations) -> dict[str, Any]:
    return json.loads(where.claude_json.read_text(encoding="utf-8"))


def write_claude_json(where: Locations, servers: dict[str, Any], **other: object) -> None:
    where.claude_json.write_text(
        json.dumps({"numStartups": 4, "mcpServers": servers, **other}), encoding="utf-8"
    )
