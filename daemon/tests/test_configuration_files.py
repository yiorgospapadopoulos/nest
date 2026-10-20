"""B97: the import line, skill folders and MCP servers in each engine's shape."""

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from nestd.claude_code.extensions import front_matter
from nestd.configuration.errors import ChangedOnDiskError
from nestd.configuration.instructions import (
    has_import,
    own_instructions,
    with_import,
    without_import,
)
from nestd.configuration.mcp import (
    NO_SSE,
    VARIABLES,
    McpServer,
    ServersFile,
    from_claude,
    from_codex,
    to_claude,
    to_codex,
)
from nestd.configuration.skills import create_skill, find_skills, valid_name
from nestd.errors import InvalidInputError
from tests.configuration_support import skill

LINE = "@/Users/me/.codex/AGENTS.md"


def test_the_import_line() -> None:
    text = "# Mine\n\nUse tabs.\n"

    added = with_import(text, LINE)

    assert added == f"{LINE}\n\n# Mine\n\nUse tabs.\n"
    assert has_import(added, LINE)
    assert with_import(added, LINE) == added
    assert with_import("", LINE) == f"{LINE}\n"
    assert without_import(added, LINE) == text
    assert own_instructions(f"  {LINE}  \n\n", LINE) == ""
    assert not has_import(f"see {LINE}", LINE)


def test_skills_are_found_at_any_depth_once(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill(root, "release")
    skill(root / "synced", "chrome-browser", description=None)
    skill(root / ".hidden", "secret")
    (root / "notes").mkdir()
    (root / "notes" / "readme.md").write_text("x", encoding="utf-8")
    (root / "loop").symlink_to(root)
    (root / "file.md").write_text("x", encoding="utf-8")

    found = find_skills(root)

    assert [(s.name, s.description) for s in found] == [
        ("chrome-browser", None),
        ("release", "Does things"),
    ]
    assert found[1].folder == root / "release"
    assert find_skills(tmp_path / "missing") == []


def test_a_new_skill_has_front_matter(tmp_path: Path) -> None:
    file = create_skill(tmp_path, "notes", "Takes  notes:\nfast é")

    text = file.read_text(encoding="utf-8")
    assert text == '---\nname: notes\ndescription: "Takes notes: fast é"\n---\n\n'
    assert find_skills(tmp_path)[0].description == "Takes notes: fast é"
    with pytest.raises(ChangedOnDiskError):
        create_skill(tmp_path, "notes", "again")
    assert valid_name("a-1")
    assert not valid_name("A")
    assert not valid_name("-a")
    assert not valid_name("a" * 65)


def test_stdio_servers_convert_both_ways() -> None:
    server = McpServer(transport="stdio", command="npx", args=["-y", "ctx"], env={"A": "1"})

    table, reason = to_codex(server)

    assert reason is None
    assert table == {"command": "npx", "args": ["-y", "ctx"], "env": {"A": "1"}}
    assert from_codex(table) == server
    assert to_codex(McpServer(transport="stdio", command="x"))[0] == {"command": "x"}
    assert server.summary() == "npx -y ctx"
    assert to_claude(server) == {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "ctx"],
        "env": {"A": "1"},
    }


def test_http_servers_convert_bearer_variables() -> None:
    server = McpServer(
        transport="http",
        url="https://mcp.example/mcp",
        headers={"Authorization": "Bearer ${TOKEN}", "X-Team": "nest"},
    )

    table, reason = to_codex(server)

    assert reason is None
    assert table == {
        "url": "https://mcp.example/mcp",
        "bearer_token_env_var": "TOKEN",
        "http_headers": {"X-Team": "nest"},
    }
    assert from_codex(table) == server
    assert server.summary() == "https://mcp.example/mcp"
    assert to_claude(server)["headers"] == server.headers
    plain = McpServer(transport="http", url="https://a")
    assert to_codex(plain) == ({"url": "https://a"}, None)
    assert to_claude(plain) == {"type": "http", "url": "https://a"}


@pytest.mark.parametrize(
    ("server", "reason"),
    [
        (McpServer(transport="sse", url="https://a/sse"), NO_SSE),
        (McpServer(transport="stdio", command="x", env={"K": "${KEY}"}), VARIABLES),
        (McpServer(transport="stdio", command="x", args=["${HOME}/a"]), VARIABLES),
        (McpServer(transport="http", url="https://a", headers={"X": "${V}"}), VARIABLES),
        (McpServer(transport="http", url="https://${HOST}/mcp"), VARIABLES),
        (
            McpServer(transport="http", url="https://a", headers={"X-Key": "Bearer ${V}"}),
            VARIABLES,
        ),
    ],
)
def test_servers_codex_cannot_take(server: McpServer, reason: str) -> None:
    assert to_codex(server) == (None, reason)


def test_incomplete_servers_are_refused() -> None:
    with pytest.raises(ValidationError, match="needs a command"):
        McpServer(transport="stdio")
    with pytest.raises(ValidationError, match="needs a url"):
        McpServer(transport="http")


def test_reading_entries_nest_does_not_understand() -> None:
    assert from_claude("x") is None
    assert from_claude({"type": "ws", "url": "x"}) is None
    assert from_claude({"type": "http"}) is None
    assert from_claude({"command": "x", "args": None}) == McpServer(transport="stdio", command="x")
    assert from_codex(["x"]) is None
    assert from_codex({"enabled": True}) is None
    assert from_codex({"command": "x", "args": [1, "a"], "env": "bad"}) == McpServer(
        transport="stdio", command="x", args=["a"]
    )


def test_a_servers_file_is_changed_by_key(tmp_path: Path) -> None:
    path = tmp_path / ".claude.json"
    original = {"numStartups": 3, "mcpServers": {"bad": "x"}, "oauthAccount": {"a": 1}}
    path.write_text(json.dumps(original), encoding="utf-8")
    os.chmod(path, 0o600)  # noqa: PTH101
    servers = ServersFile(path)

    servers.put("ctx", McpServer(transport="http", url="https://a"))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert list(data) == ["numStartups", "mcpServers", "oauthAccount"]
    assert data["mcpServers"] == {"bad": "x", "ctx": {"type": "http", "url": "https://a"}}
    assert path.stat().st_mode & 0o777 == 0o600
    assert servers.servers() == {"ctx": McpServer(transport="http", url="https://a")}
    assert servers.remove("ctx")
    assert not servers.remove("ctx")


def test_missing_or_odd_servers_files(tmp_path: Path) -> None:
    missing = ServersFile(tmp_path / "new" / ".mcp.json")
    assert missing.servers() == {}
    assert not missing.remove("x")
    missing.put("x", McpServer(transport="stdio", command="x"))
    assert json.loads(missing.path.read_text(encoding="utf-8"))["mcpServers"]["x"]["command"] == "x"

    odd = tmp_path / "odd.json"
    odd.write_text('{"mcpServers": []}', encoding="utf-8")
    assert ServersFile(odd).servers() == {}
    assert not ServersFile(odd).remove("x")
    ServersFile(odd).put("x", McpServer(transport="stdio", command="x"))
    assert list(ServersFile(odd).servers()) == ["x"]

    for text in ("{", "[]"):
        odd.write_text(text, encoding="utf-8")
        with pytest.raises(InvalidInputError):
            ServersFile(odd).servers()


@pytest.mark.parametrize(
    ("line", "value"),
    [
        ('description: "Say \\"hi\\" to C:\\\\x"', 'Say "hi" to C:\\x'),
        ('description: "tab\\there\\nnew \\u00e9"', "tab\there\nnew é"),
        ("description: 'It''s here'", "It's here"),
        ('description: "closed" # a comment', "closed"),
        ("description: 'closed' trailing", "closed"),
        ('description: "never closed', "never closed"),
        ("description: 'never closed", "never closed"),
        ('description: "odd \\q and \\uZZ"', "odd q and uZZ"),
        ('description: "ends in \\', "ends in \\"),
        ("description: plain 'words' here", "plain 'words' here"),
        ("description: it's plain", "it's plain"),
    ],
)
def test_front_matter_values_are_unquoted(line: str, value: str) -> None:
    assert front_matter(f"---\n{line}\n---\n")["description"] == value
