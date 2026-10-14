"""The thinking level Claude Code uses when none is chosen, from its settings (IMP-07).

Only `effortLevel` and `modelSettings.<model>.effortLevel` of Claude Code's user settings
file (`~/.claude/settings.json`) are taken; the rest of the file is never kept, logged or
served, and the file is never written.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from harness.providers.base import ModelOption

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EffortSettings:
    # `effortLevel`: every model's, unless the model has its own.
    default: str | None = None
    # `modelSettings.<model>.effortLevel`, by Claude Code's model id or alias.
    per_model: dict[str, str] = field(default_factory=dict[str, str])


def effort_settings(path: Path | None) -> EffortSettings:
    """The levels the file sets; none when there is no file or it cannot be read."""
    if path is None:
        return EffortSettings()
    try:
        data: object = json.loads(path.read_bytes().decode("utf-8"))
    except FileNotFoundError:
        return EffortSettings()
    except (OSError, ValueError) as error:
        # The kind only: the file can hold other settings and secrets.
        logger.warning("could not read Claude Code's settings (%s)", type(error).__name__)
        return EffortSettings()
    if not isinstance(data, dict):
        return EffortSettings()
    settings = cast("dict[str, object]", data)
    default = settings.get("effortLevel")
    models = settings.get("modelSettings")
    per_model: dict[str, str] = {}
    for name, entry in cast(
        "dict[str, object]", models if isinstance(models, dict) else {}
    ).items():
        level = (
            cast("dict[str, object]", entry).get("effortLevel") if isinstance(entry, dict) else None
        )
        if isinstance(level, str):
            per_model[name] = level
    return EffortSettings(default if isinstance(default, str) else None, per_model)


def claude_code_effort(model: ModelOption, settings: EffortSettings) -> str | None:
    """The level Claude Code uses for `model` when none is chosen; None when the settings
    set none the model takes.
    """
    keys = [key for key in (model.resolved_model, model.value) if key is not None]
    level = next((settings.per_model[key] for key in keys if key in settings.per_model), None)
    level = level or settings.default
    return level if level in model.effort_levels else None
