"""Nest fails closed on an ACP engine's reads and fetches (B107): what it cannot judge is
asked of the user.
"""

import json
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.config.models import PermissionMode
from nestd.providers.acp_events import AcpStream, ToolCall
from nestd.providers.acp_permissions import AcpPermissions, AcpRules
from nestd.providers.base import (
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    QuestionAnswer,
    QuestionRequest,
)
from tests.recording_sink import RecordingSink


class Handler:
    def __init__(self) -> None:
        self.requests: list[PermissionRequest] = []

    async def decide(self, request: PermissionRequest) -> PermissionDecision:
        self.requests.append(request)
        return PermissionDecision("deny")

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        raise AssertionError

    async def review_plan(self, request: PlanRequest) -> PlanDecision:
        raise AssertionError


async def verdict(
    tmp_path: Path, fields: dict[str, JsonValue], mode: PermissionMode = "default"
) -> tuple[str, Handler]:
    handler = Handler()
    rules = AcpRules(mode, guarded=False, folders=(tmp_path / "repo", tmp_path / "extra"))
    permissions = AcpPermissions(handler, lambda: rules, AcpStream(RecordingSink(), {}))
    call = ToolCall("call-1")
    call.update(fields)
    return await permissions.verdict(call), handler


@pytest.mark.parametrize(
    "fields",
    [
        {"rawInput": {"absolute_path": "{repo}/a.py"}},
        {"rawInput": {"dir_path": "{extra}"}},
        {"rawInput": {"paths": ["{repo}/a.py", "{extra}/b.py"]}},
        {"rawInput": {"file_path": "{repo}/a.py"}},
        {"locations": [{"path": "{repo}/a.py"}]},
    ],
)
async def test_a_read_inside_the_chats_folders_is_allowed(
    tmp_path: Path, fields: dict[str, JsonValue]
) -> None:
    filled = _filled(fields, tmp_path)

    found, handler = await verdict(tmp_path, {"kind": "read", "title": "read", **filled})

    assert found == "allow"
    assert handler.requests == []


@pytest.mark.parametrize("kind", ["read", "search"])
async def test_a_read_without_a_path_nest_knows_is_asked(tmp_path: Path, kind: str) -> None:
    found, handler = await verdict(
        tmp_path, {"kind": kind, "title": "secrets", "rawInput": {"where": "/etc"}}
    )

    assert found == "reject"
    assert len(handler.requests) == 1


async def test_a_read_with_one_path_outside_the_folders_is_asked(tmp_path: Path) -> None:
    fields = _filled(
        {"rawInput": {"paths": ["{repo}/a.py", "/etc/passwd"]}, "locations": []}, tmp_path
    )

    found, handler = await verdict(tmp_path, {"kind": "read", "title": "read", **fields})

    assert found == "reject"
    assert len(handler.requests) == 1


@pytest.mark.parametrize("mode", ["default", "acceptEdits", "plan"])
async def test_a_fetch_is_asked(tmp_path: Path, mode: PermissionMode) -> None:
    found, handler = await verdict(
        tmp_path,
        {
            "kind": "fetch",
            "title": "https://example.com",
            "rawInput": {"url": "https://example.com"},
        },
        mode,
    )

    assert found == "reject"
    [asked] = handler.requests
    assert (asked.tool_name, asked.tool_input) == ("WebFetch", {"url": "https://example.com"})


@pytest.mark.parametrize(
    "fields",
    [
        # A command whose text starts like one of Nest's tools.
        {"title": "nest_memory_read(x); git push origin main", "rawInput": {}},
        {"title": "nest_memory_read", "rawInput": {"command": "git push origin main"}},
        {"title": "memory_read(x) && git push origin main", "rawInput": {}},
    ],
)
async def test_a_call_that_only_looks_like_a_nest_tool_is_judged(
    tmp_path: Path, fields: dict[str, JsonValue]
) -> None:
    """Regression (security review): a title merely starting with a Nest tool's name, or a
    call carrying a command, passed as Nest's own tool without being judged.
    """
    handler = Handler()
    nest = {"nest": frozenset({"memory_read"})}
    rules = AcpRules("bypassPermissions", guarded=True, folders=(tmp_path,), nest=nest)
    permissions = AcpPermissions(handler, lambda: rules, AcpStream(RecordingSink(), nest))
    call = ToolCall("call-1")
    call.update(fields)

    assert await permissions.verdict(call) == "reject"


async def test_a_bare_tool_name_another_server_could_share_is_asked(tmp_path: Path) -> None:
    handler = Handler()
    nest = {"nest": frozenset({"memory_read"})}
    rules = AcpRules("default", guarded=True, folders=(tmp_path,), nest=nest)
    permissions = AcpPermissions(handler, lambda: rules, AcpStream(RecordingSink(), nest))
    call = ToolCall("call-1")
    call.update({"title": "memory_read(key: notes)", "rawInput": {}})

    assert await permissions.verdict(call) == "reject"
    [asked] = handler.requests
    assert asked.tool_name != "mcp__nest__memory_read"


async def test_nests_own_tool_still_passes(tmp_path: Path) -> None:
    handler = Handler()
    nest = {"nest": frozenset({"memory_read"})}
    rules = AcpRules("default", guarded=True, folders=(tmp_path,), nest=nest)
    permissions = AcpPermissions(handler, lambda: rules, AcpStream(RecordingSink(), nest))
    call = ToolCall("call-1")
    call.update({"title": "nest_memory_read", "rawInput": {"key": "notes"}})

    assert await permissions.verdict(call) == "allow"
    assert handler.requests == []


def _filled(fields: dict[str, JsonValue], tmp_path: Path) -> dict[str, JsonValue]:
    """`{repo}` and `{extra}` as the test's folders."""
    raw = json.dumps(fields)
    raw = raw.replace("{repo}", str(tmp_path / "repo")).replace("{extra}", str(tmp_path / "extra"))
    filled: dict[str, JsonValue] = json.loads(raw)
    return filled
