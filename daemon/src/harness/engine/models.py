"""The model list and account clients show (D038)."""

from datetime import datetime

from pydantic import BaseModel

from harness.providers.base import ModelOption

_LEVELS = ["low", "medium", "high", "xhigh", "max"]

# Claude Code's aliases, offered until the engine reported its own list.
FALLBACK_MODELS = (
    ModelOption(
        value="default",
        display_name="Default (recommended)",
        description="Claude Code's default model",
        effort_levels=_LEVELS,
        supports_effort=True,
    ),
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
