"""Engine folders in `tmp_path` for the configuration tests (B97); never the real ones."""

import os
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from nestd.claude_code.extensions import front_matter
from nestd.configuration.locations import Locations
from nestd.providers.codex_rpc import JsonObject
from tests.codex_support import FakeAppServer


def locations(tmp_path: Path) -> Locations:
    where = Locations(
        claude_dir=tmp_path / "claude",
        claude_json=tmp_path / "claude.json",
        codex_home=tmp_path / "codex",
    )
    where.claude_dir.mkdir(parents=True, exist_ok=True)
    where.codex_home.mkdir(parents=True, exist_ok=True)
    return where


def skill(folder: Path, name: str, description: str | None = "Does things") -> Path:
    """A skill folder with its SKILL.md; returns the SKILL.md."""
    file = folder / name / "SKILL.md"
    file.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"name: {name}"]
    if description is not None:
        lines.append(f"description: {description}")
    file.write_text("\n".join([*lines, "---", "", "Body", ""]), encoding="utf-8")
    return file


class FakeCodexSetup:
    """Codex's setup methods on the fake app-server, as Codex 0.163 answers them: skills
    found under its skills folders (links followed; a SKILL.md without a description is an
    error), its user config's MCP tables with a version, plugins and hooks.
    """

    def __init__(self, server: FakeAppServer, where: Locations) -> None:
        self.where = where
        # More skill folders Codex reads, such as `~/.agents/skills`.
        self.roots: list[Path] = [where.codex_skills]
        self.servers: dict[str, JsonValue] = {}
        self.version = 1
        self.disabled: set[str] = set()
        self.hooks: list[JsonValue] = [
            {"source": "user", "eventName": "stop"},
            {"source": "plugin", "eventName": "stop"},
        ]
        self.marketplaces: list[JsonValue] = [
            {
                "name": "openai-curated",
                "path": "/codex/marketplaces/curated",
                "plugins": [
                    plugin("figma@openai-curated", "figma", "Design files", installed=True),
                    plugin("linear@openai-curated", "linear", "Issues", installed=False),
                ],
            }
        ]
        server.answers["skills/list"] = self._skills
        server.answers["skills/config/write"] = self._write_skill
        server.answers["config/read"] = self._read
        server.answers["config/batchWrite"] = self._batch
        server.answers["plugin/list"] = lambda _params: {"marketplaces": self.marketplaces}
        server.answers["plugin/installed"] = lambda _params: {"marketplaces": self.marketplaces}
        server.answers["hooks/list"] = lambda _params: {
            "data": [{"cwd": "/", "hooks": self.hooks, "errors": [], "warnings": []}]
        }

    def _skills(self, _params: JsonObject) -> JsonObject:
        skills: list[JsonValue] = []
        errors: list[JsonValue] = []
        for root in self.roots:
            for folder, _dirs, files in os.walk(root, followlinks=True):
                if "SKILL.md" not in files:
                    continue
                path = str(Path(folder) / "SKILL.md")
                fields = front_matter(Path(path).read_text(encoding="utf-8"))
                if "description" not in fields:
                    errors.append({"path": path, "message": "missing field `description`"})
                    continue
                skills.append(
                    {
                        "name": fields.get("name", Path(folder).name),
                        "description": fields["description"],
                        "path": path,
                        "enabled": path not in self.disabled,
                        "scope": "user",
                        "pluginId": None,
                    }
                )
        skills.append(
            {
                "name": "imagegen",
                "description": "System",
                "path": "/codex/skills/.system/imagegen/SKILL.md",
                "enabled": True,
                "scope": "system",
            }
        )
        return {"data": [{"cwd": "/", "skills": skills, "errors": errors}]}

    def _write_skill(self, params: JsonObject) -> JsonObject:
        path = str(params["path"])
        if params["enabled"]:
            self.disabled.discard(path)
        else:
            self.disabled.add(path)
        return {"effectiveEnabled": params["enabled"]}

    def _read(self, _params: JsonObject) -> JsonObject:
        user: JsonObject = {
            "name": {"type": "user", "file": str(self.where.codex_config), "profile": None},
            "version": f"v{self.version}",
            "config": {"model": "gpt-6", "mcp_servers": dict(self.servers)},
        }
        system: JsonObject = {"name": {"type": "system", "file": "/etc"}, "version": "s"}
        return {"config": {}, "origins": {}, "layers": [system, user]}

    def _batch(self, params: JsonObject) -> JsonObject:
        assert params["expectedVersion"] == f"v{self.version}"
        for raw in cast("list[JsonObject]", params["edits"]):
            assert raw["mergeStrategy"] == "replace"
            name = str(raw["keyPath"]).removeprefix("mcp_servers.")
            if raw["value"] is None:
                self.servers.pop(name, None)
            else:
                self.servers[name] = raw["value"]
        self.version += 1
        return {"status": "ok", "version": f"v{self.version}", "filePath": "x"}


def plugin(plugin_id: str, name: str, description: str, *, installed: bool) -> JsonObject:
    return {
        "id": plugin_id,
        "name": name,
        "installed": installed,
        "enabled": installed,
        "version": "1.0.0",
        "interface": {"shortDescription": description},
        "source": {"type": "local", "path": "/x"},
    }
