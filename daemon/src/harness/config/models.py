"""Typed models for the TOML files in the user config directory."""

from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Effort = Literal["low", "medium", "high", "xhigh", "max"]
PermissionMode = Literal["default", "acceptEdits", "bypassPermissions", "plan"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerSettings(_Strict):
    # The host is always 127.0.0.1 (D014), so only the port is configurable.
    port: int = Field(default=8765, ge=1, le=65535)


class AgentDefaults(_Strict):
    model: str | None = None
    effort: Effort | None = None
    permission_mode: PermissionMode = "default"
    # Idle agent processes are closed after this long and resumed on the next message.
    idle_close_minutes: int = Field(default=10, ge=1)


class ModulesSettings(_Strict):
    enabled: list[str] = Field(default_factory=list[str])


class Settings(_Strict):
    server: ServerSettings = Field(default_factory=ServerSettings)
    agents: AgentDefaults = Field(default_factory=AgentDefaults)
    modules: ModulesSettings = Field(default_factory=ModulesSettings)


class WorktreeConfig(_Strict):
    default: bool = True
    link: list[str] = Field(default_factory=list[str])
    setup: list[str] = Field(default_factory=list[str])
    # Applies to each setup command separately.
    setup_timeout_seconds: int = Field(default=900, ge=1)

    @field_validator("link")
    @classmethod
    def _links_stay_inside_repo(cls, links: list[str]) -> list[str]:
        for link in links:
            path = PurePosixPath(link)
            if not link or path.is_absolute() or ".." in path.parts or path == PurePosixPath():
                msg = f"link {link!r} must be a relative path inside the repository"
                raise ValueError(msg)
        return links


class RepoConfig(_Strict):
    # The name doubles as the config file name, so it must be a safe file name.
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    path: Path
    default_branch: str = "main"
    worktree: WorktreeConfig = Field(default_factory=WorktreeConfig)


class TaskTemplate(_Strict):
    name: str
    prompt: str
    repo: str | None = None
    model: str | None = None
    effort: Effort | None = None
    permission_mode: PermissionMode | None = None
