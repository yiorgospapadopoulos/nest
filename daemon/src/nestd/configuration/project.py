"""A project's own setup in Settings > Project (B97, contract rule 8): Claude's files only.

Its MCP servers live in the repo's `.mcp.json` and are Claude only; Nest never writes a
repo's `.codex/config.toml`.
"""

import asyncio
from pathlib import Path

from nestd.configuration.backups import Backups
from nestd.configuration.errors import UnknownItemError
from nestd.configuration.locations import REPO_SKILLS
from nestd.configuration.mcp import McpServer, McpServerSummary, ServersFile
from nestd.configuration.models import ProjectConfiguration, ProjectFile, SkillItem
from nestd.configuration.skills import create_skill, find_skills, valid_name
from nestd.errors import InvalidInputError

MCP_FILE = ".mcp.json"


def read_project(repo: Path) -> ProjectConfiguration:
    return ProjectConfiguration(
        instructions=[
            ProjectFile(path=str(repo / name), exists=(repo / name).is_file())
            for name in ("AGENTS.md", "CLAUDE.md")
        ],
        skills=[
            SkillItem(
                name=skill.name,
                description=skill.description,
                path=str(skill.file),
                source="project",
                read_only=False,
            )
            for skill in find_skills(repo / REPO_SKILLS)
        ],
        mcp_servers=[
            McpServerSummary(name=name, summary=server.summary(), transport=server.transport)
            for name, server in sorted(ServersFile(repo / MCP_FILE).servers().items())
        ],
    )


class ProjectSetup:
    def __init__(self, backups: Backups) -> None:
        self._backups = backups
        self._lock = asyncio.Lock()

    async def read(self, repo: Path) -> ProjectConfiguration:
        return await asyncio.to_thread(read_project, repo)

    async def put_server(self, repo: Path, name: str, server: McpServer) -> ProjectConfiguration:
        async with self._lock:
            await asyncio.to_thread(self._put, repo, name, server)
        return await self.read(repo)

    async def delete_server(self, repo: Path, name: str) -> ProjectConfiguration:
        """404 when `.mcp.json` has no such server."""
        async with self._lock:
            await asyncio.to_thread(self._delete, repo, name)
        return await self.read(repo)

    async def create_skill(self, repo: Path, name: str, description: str) -> ProjectConfiguration:
        """`.claude/skills/<name>/SKILL.md`; 422 for a bad name, 409 when it exists."""
        if not valid_name(name):
            msg = f"{name!r} is not a skill name: lowercase letters, digits and dashes"
            raise InvalidInputError(msg)
        async with self._lock:
            self._backups.start("project-skill").save(repo / REPO_SKILLS / name)
            await asyncio.to_thread(create_skill, repo / REPO_SKILLS, name, description)
        return await self.read(repo)

    def _put(self, repo: Path, name: str, server: McpServer) -> None:
        self._backups.start("project-mcp").save(repo / MCP_FILE)
        ServersFile(repo / MCP_FILE).put(name, server)

    def _delete(self, repo: Path, name: str) -> None:
        file = ServersFile(repo / MCP_FILE)
        if name not in file.servers():
            raise UnknownItemError(f"{MCP_FILE} has no server {name!r}")
        self._backups.start("project-mcp").save(repo / MCP_FILE)
        file.remove(name)
