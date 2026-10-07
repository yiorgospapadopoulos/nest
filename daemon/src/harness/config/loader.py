"""Read and write the TOML files in the user config directory."""

import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import BaseModel, ValidationError

from harness.config.errors import ConfigError
from harness.config.models import (
    AgentChoices,
    AgentDefaults,
    NotificationSettings,
    RepoConfig,
    Settings,
    StuckSettings,
    TaskTemplate,
    UsageSettings,
)
from harness.paths import AppPaths


def load_settings(paths: AppPaths) -> Settings:
    file = paths.settings_file
    if not file.exists():
        settings = Settings()
        _write_toml(file, _dump(settings))
        return settings
    return _parse(file, Settings)


def load_repos(paths: AppPaths) -> list[RepoConfig]:
    return _load_named(paths.repos_dir, RepoConfig, "repo")


def load_templates(paths: AppPaths) -> list[TaskTemplate]:
    return _load_named(paths.templates_dir, TaskTemplate, "template")


def save_repo(paths: AppPaths, repo: RepoConfig) -> None:
    data = _dump(repo)
    if repo.git:
        del data["git"]  # only plain folders write `git = false` (D041)
    _write_toml(paths.repos_dir / f"{repo.name}.toml", data)


def delete_repo(paths: AppPaths, name: str) -> None:
    (paths.repos_dir / f"{name}.toml").unlink(missing_ok=True)


def save_notifications(
    paths: AppPaths, notifications: NotificationSettings
) -> NotificationSettings:
    """Replace the `[notifications]` section of settings.toml, keeping every other section."""
    return _save_section(paths, "notifications", notifications).notifications


def save_usage(paths: AppPaths, usage: UsageSettings) -> UsageSettings:
    """Replace the `[usage]` section of settings.toml, keeping every other section."""
    return _save_section(paths, "usage", usage).usage


def save_stuck(paths: AppPaths, stuck: StuckSettings) -> StuckSettings:
    """Replace the `[stuck]` section of settings.toml, keeping every other section."""
    return _save_section(paths, "stuck", stuck).stuck


def save_agent_defaults(paths: AppPaths, choices: AgentChoices) -> AgentDefaults:
    """Set the client-editable keys of `[agents]`, keeping its other keys and every other
    section. A null model or effort removes the key, so Claude Code's default applies.
    """
    file = paths.settings_file
    data = _read_toml(file) if file.exists() else {}
    agents = {
        key: value
        for key, value in data.get("agents", {}).items()
        if key not in {"model", "effort", "permission_mode", "default_mode"}
    }
    chosen = {
        "model": choices.model,
        "effort": choices.effort,
        "permission_mode": choices.permission_mode,
        "default_mode": choices.mode,
    }
    data["agents"] = {key: value for key, value in chosen.items() if value is not None} | agents
    settings = _validate(file, Settings, data)
    _write_toml(file, data)
    return settings.agents


def _save_section(paths: AppPaths, name: str, section: BaseModel) -> Settings:
    """The file is re-read first so edits made since the daemon started are kept; it is only
    written when the result is valid, and atomically. Comments are not preserved.
    """
    file = paths.settings_file
    data = _read_toml(file) if file.exists() else {}
    data[name] = _dump(section)
    settings = _validate(file, Settings, data)
    _write_toml(file, data)
    return settings


def _load_named[M: RepoConfig | TaskTemplate](
    directory: Path, model: type[M], kind: str
) -> list[M]:
    items: list[M] = []
    seen: dict[str, Path] = {}
    for file in sorted(directory.glob("*.toml")):
        item = _parse(file, model)
        if item.name in seen:
            msg = f"{file}: duplicate {kind} name {item.name!r} (also in {seen[item.name]})"
            raise ConfigError(msg)
        seen[item.name] = file
        items.append(item)
    return items


def _parse[M: BaseModel](file: Path, model: type[M]) -> M:
    return _validate(file, model, _read_toml(file))


def _read_toml(file: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        msg = f"{file}: invalid TOML: {error}"
        raise ConfigError(msg) from error


def _validate[M: BaseModel](file: Path, model: type[M], data: dict[str, Any]) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        msg = f"{file}: {_summarize(error)}"
        raise ConfigError(msg) from error


def _summarize(error: ValidationError) -> str:
    parts: list[str] = []
    for detail in error.errors():
        location = ".".join(str(part) for part in detail["loc"])
        parts.append(f"{location}: {detail['msg']}")
    return "; ".join(parts)


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)


def _write_toml(file: Path, data: dict[str, Any]) -> None:
    """Write through a temporary file and a rename, so a reader never sees half a file."""
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(f"{file.name}.tmp")
    temporary.write_text(tomli_w.dumps(data), encoding="utf-8")
    temporary.replace(file)
