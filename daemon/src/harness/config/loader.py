"""Read and write the TOML files in the user config directory."""

import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from pydantic import BaseModel, ValidationError

from harness.config.errors import ConfigError
from harness.config.models import RepoConfig, Settings, TaskTemplate
from harness.paths import AppPaths


def load_settings(paths: AppPaths) -> Settings:
    file = paths.settings_file
    if not file.exists():
        settings = Settings()
        _write_toml(file, settings)
        return settings
    return _parse(file, Settings)


def load_repos(paths: AppPaths) -> list[RepoConfig]:
    return _load_named(paths.repos_dir, RepoConfig, "repo")


def load_templates(paths: AppPaths) -> list[TaskTemplate]:
    return _load_named(paths.templates_dir, TaskTemplate, "template")


def save_repo(paths: AppPaths, repo: RepoConfig) -> None:
    _write_toml(paths.repos_dir / f"{repo.name}.toml", repo)


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
    try:
        data: dict[str, Any] = tomllib.loads(file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        msg = f"{file}: invalid TOML: {error}"
        raise ConfigError(msg) from error
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


def _write_toml(file: Path, model: BaseModel) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    data = model.model_dump(mode="json", exclude_none=True)
    file.write_text(tomli_w.dumps(data), encoding="utf-8")
