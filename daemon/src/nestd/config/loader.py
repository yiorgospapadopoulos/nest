"""Read and write the TOML files in the user config directory."""

import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import BaseModel, ValidationError

from nestd.config.errors import ConfigError
from nestd.config.models import (
    AgentChoices,
    AgentDefaults,
    ConfigurationSettings,
    NotificationSettings,
    PixieDefaults,
    ProjectSettings,
    RepoConfig,
    Settings,
    StorageSettings,
    StuckSettings,
    TaskTemplate,
    UsageSettings,
)
from nestd.paths import AppPaths


def load_settings(paths: AppPaths) -> Settings:
    file = paths.settings_file
    if not file.exists():
        settings = Settings()
        _write_toml(file, _dump(settings))
        return settings
    return _parse(file, Settings)


def load_project_order(paths: AppPaths) -> list[str]:
    """The saved project order; unlike `load_settings`, a missing file is not created."""
    file = paths.settings_file
    if not file.exists():
        return []
    return _parse(file, Settings).projects.order


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
    return _save_section(paths, "notifications", _dump(notifications)).notifications


def save_usage(paths: AppPaths, usage: UsageSettings) -> UsageSettings:
    """Replace the `[usage]` section of settings.toml, keeping every other section."""
    data = _dump(usage)
    if usage.warn_percent is None:
        data["warn_percent"] = 0  # TOML has no null
    return _save_section(paths, "usage", data).usage


def save_stuck(paths: AppPaths, stuck: StuckSettings) -> StuckSettings:
    """Replace the `[stuck]` section of settings.toml, keeping every other section."""
    return _save_section(paths, "stuck", _dump(stuck)).stuck


def save_storage(paths: AppPaths, storage: StorageSettings) -> StorageSettings:
    """Replace the `[storage]` section of settings.toml, keeping every other section."""
    return _save_section(paths, "storage", _dump(storage)).storage


def save_pixie_defaults(paths: AppPaths, pixies: PixieDefaults) -> PixieDefaults:
    """Replace the `[pixies]` section of settings.toml, keeping every other section."""
    return _save_section(paths, "pixies", _dump(pixies)).pixies


def save_configuration(
    paths: AppPaths, configuration: ConfigurationSettings
) -> ConfigurationSettings:
    """Replace the `[configuration]` section of settings.toml, keeping every other section."""
    return _save_section(paths, "configuration", _dump(configuration)).configuration


def save_project_order(paths: AppPaths, order: list[str]) -> list[str]:
    """Replace the `[projects]` section of settings.toml, keeping every other section."""
    section = _dump(ProjectSettings(order=order))
    return _save_section(paths, "projects", section).projects.order


def save_agent_defaults(paths: AppPaths, choices: AgentChoices) -> AgentDefaults:
    """Set the client-editable keys of `[agents]`, keeping its other keys and every other
    section. A null removes the key (TOML has none): a model without thinking levels has
    no effort.
    """
    file = paths.settings_file
    data = _read_toml(file) if file.exists() else {}
    agents = {
        key: value
        for key, value in data.get("agents", {}).items()
        if key not in {"provider", "model", "effort", "permission_mode", "default_mode"}
    }
    chosen = {
        "provider": choices.provider,
        "model": choices.model,
        "effort": choices.effort,
        "permission_mode": choices.permission_mode,
        "default_mode": choices.mode,
    }
    data["agents"] = {key: value for key, value in chosen.items() if value is not None} | agents
    settings = _validate(file, Settings, data)
    _write_toml(file, data)
    return settings.agents


def _save_section(paths: AppPaths, name: str, section: dict[str, Any]) -> Settings:
    """The file is re-read first so edits made since the daemon started are kept; it is only
    written when the result is valid, and atomically. Comments are not preserved.
    """
    file = paths.settings_file
    data = _read_toml(file) if file.exists() else {}
    data[name] = section
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
