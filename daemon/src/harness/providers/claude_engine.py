"""The models and account Claude Code reports in its initialize response (D038).

`ClaudeSDKClient.get_server_info()` returns it once the client connected, without a model
call. Entries that do not fit are skipped, so a changed engine degrades to the fallback.
"""

import re
from typing import Any, cast

from harness.providers.base import AccountInfo, EngineDetails, ModelOption

# Raw subscription types the engine may report, by their first word.
_PLANS = {
    "free": "Claude Free",
    "pro": "Claude Pro",
    "max": "Claude Max",
    "team": "Claude Team",
    "enterprise": "Claude Enterprise",
}
_SEPARATORS = re.compile(r"[\s_-]+")


def engine_details(data: dict[str, Any] | None) -> EngineDetails | None:
    """The models and account of an initialize response; None when it has neither."""
    if data is None:
        return None
    models = [option for entry in _entries(data.get("models")) if (option := _model(entry))]
    raw_account = data.get("account")
    account = (
        _account(cast("dict[str, object]", raw_account)) if isinstance(raw_account, dict) else None
    )
    if not models and account is None:
        return None
    return EngineDetails(models=models or None, account=account)


def plan_label(raw: str) -> str | None:
    """A readable plan name: "Claude Max" for "max" or "max_20x"; the engine's own label
    ("Claude Pro") is kept as it is.
    """
    text = raw.strip()
    if not text:
        return None
    if text.lower().startswith("claude "):
        return text
    words = [word for word in _SEPARATORS.split(text) if word]
    return _PLANS.get(words[0].lower()) or " ".join(word.capitalize() for word in words)


def _model(entry: dict[str, object]) -> ModelOption | None:
    value = _text(entry.get("value"))
    if value is None:
        return None
    raw_levels = entry.get("supportedEffortLevels")
    levels = [level for level in _list(raw_levels) if isinstance(level, str) and level]
    return ModelOption(
        value=value,
        display_name=_text(entry.get("displayName")) or value,
        description=_text(entry.get("description")) or "",
        effort_levels=levels,
        supports_effort=entry.get("supportsEffort") is True,
        supports_auto_mode=entry.get("supportsAutoMode") is True,
        resolved_model=_text(entry.get("resolvedModel")),
    )


def _account(data: dict[str, object]) -> AccountInfo:
    plan = _text(data.get("subscriptionType"))
    return AccountInfo(
        display_name=_text(data.get("displayName")),
        email=_text(data.get("email")),
        plan=plan_label(plan) if plan is not None else None,
        organization=_text(data.get("organization")),
    )


def _entries(raw: object) -> list[dict[str, object]]:
    return [cast("dict[str, object]", entry) for entry in _list(raw) if isinstance(entry, dict)]


def _list(raw: object) -> list[object]:
    return cast("list[object]", raw) if isinstance(raw, list) else []


def _text(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    return text or None
