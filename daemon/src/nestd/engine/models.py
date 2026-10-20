"""The model list and account clients show (D038), and the defaults Nest picks from it
when nothing is chosen (B94).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import get_args

from pydantic import BaseModel

from nestd.config.models import Effort
from nestd.providers.base import ModelOption

_LEVELS = ["low", "medium", "high", "xhigh", "max"]
# The value both engines' lists use for the entry that defers to the engine. Nest keeps
# it to learn the engine's default model but never offers it (B94).
ENGINE_DEFAULT = "default"
# The thinking level a chat gets when none is chosen (B94).
MEDIUM: Effort = "medium"
_ORDER: tuple[Effort, ...] = get_args(Effort)

# Claude Code's aliases, offered until the engine reported its own list.
FALLBACK_MODELS = (
    ModelOption(
        value="opus",
        display_name="Opus",
        description="Most capable, for complex work",
        effort_levels=_LEVELS,
        supports_effort=True,
    ),
    ModelOption(
        value="sonnet",
        display_name="Sonnet",
        description="Fast and capable, for everyday tasks",
        effort_levels=_LEVELS,
        supports_effort=True,
    ),
    ModelOption(value="haiku", display_name="Haiku", description="Fastest, for quick answers"),
)


class ModelList(BaseModel):
    """`GET /api/models`, in Claude Code's order."""

    models: list[ModelOption]
    # When the engine last reported the list; None for the built-in fallback.
    updated_at: datetime | None
    # The model the engine runs when none is named, as a value of `models` where one
    # resolves to it (B94); None while the engine has not said.
    default_model: str | None = None


def closest_effort(levels: Sequence[str]) -> Effort | None:
    """Medium, or the level nearest to it the model takes (the lower one of two as near);
    None for a model that takes no thinking level.
    """
    offered = set(levels)
    known: list[Effort] = [level for level in _ORDER if level in offered]
    if not known:
        return None
    middle = _ORDER.index(MEDIUM)
    return min(known, key=lambda level: (abs(_ORDER.index(level) - middle), _ORDER.index(level)))


def engine_default(models: Sequence[ModelOption]) -> str | None:
    """The model the engine's `default` entry stands for: the listed value it resolves to
    (the model itself before an alias of it), else that model's id; without a resolved
    default, the first real model.
    """
    real = [model for model in models if model.value != ENGINE_DEFAULT]
    entry = next((model for model in models if model.value == ENGINE_DEFAULT), None)
    resolved = None if entry is None else entry.resolved_model
    if resolved is None:
        return real[0].value if real else None
    exact = next((model.value for model in real if model.value == resolved), None)
    alias = next((model.value for model in real if model.resolved_model == resolved), None)
    return exact or alias or resolved


def listed_models(listed: ModelList) -> ModelList:
    """The list clients get: real models only, with the engine's default named."""
    return listed.model_copy(
        update={
            "models": [model for model in listed.models if model.value != ENGINE_DEFAULT],
            "default_model": engine_default(listed.models),
        }
    )
