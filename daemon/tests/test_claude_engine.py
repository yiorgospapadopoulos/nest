from typing import Any

import pytest

from harness.providers.base import AccountInfo, EngineDetails, ModelOption
from harness.providers.claude_engine import engine_details, plan_label

LEVELS = ["low", "medium", "high", "xhigh", "max"]


def model(value: str, name: str, **extra: object) -> dict[str, object]:
    return {
        "value": value,
        "resolvedModel": f"claude-{value}",
        "displayName": name,
        "description": f"{name} for work",
        **extra,
    }


def test_models_keep_the_engine_order_and_their_effort_levels() -> None:
    info = {
        "models": [
            model(
                "default",
                "Default (recommended)",
                supportsEffort=True,
                supportedEffortLevels=LEVELS,
                supportsFastMode=True,
                supportsAutoMode=True,
            ),
            model("haiku", "Haiku 4.5"),
            model(
                "claude-opus-4-6",
                "Opus 4.6",
                supportsEffort=True,
                supportedEffortLevels=["low", "medium", "high", "max"],
            ),
        ]
    }

    details = engine_details(info)

    assert details == EngineDetails(
        models=[
            ModelOption(
                value="default",
                display_name="Default (recommended)",
                description="Default (recommended) for work",
                effort_levels=LEVELS,
                supports_effort=True,
                supports_auto_mode=True,
                resolved_model="claude-default",
            ),
            ModelOption(
                value="haiku",
                display_name="Haiku 4.5",
                description="Haiku 4.5 for work",
                resolved_model="claude-haiku",
            ),
            ModelOption(
                value="claude-opus-4-6",
                display_name="Opus 4.6",
                description="Opus 4.6 for work",
                effort_levels=["low", "medium", "high", "max"],
                supports_effort=True,
                resolved_model="claude-claude-opus-4-6",
            ),
        ]
    )


def test_malformed_model_entries_are_skipped_and_missing_text_has_fallbacks() -> None:
    info = {
        "models": [
            "opus",
            {"displayName": "No value"},
            {"value": ""},
            {"value": "sonnet", "supportedEffortLevels": "high"},
            {"value": "opus", "displayName": "", "description": None},
            {
                "value": "fable",
                "supportedEffortLevels": ["high", 3],
                "supportsEffort": "yes",
                "supportsAutoMode": "yes",
                "resolvedModel": 5,
            },
        ]
    }

    details = engine_details(info)

    assert details is not None
    assert details.models == [
        ModelOption(value="sonnet", display_name="sonnet", description=""),
        ModelOption(value="opus", display_name="opus", description=""),
        ModelOption(value="fable", display_name="fable", description="", effort_levels=["high"]),
    ]


@pytest.mark.parametrize("models", [None, "x", [], [{"value": 3}]])
def test_without_usable_models_the_list_is_unknown(models: object) -> None:
    details = engine_details({"models": models, "account": {"subscriptionType": "Claude Pro"}})

    assert details == EngineDetails(account=AccountInfo(plan="Claude Pro"))


def test_the_account_maps_to_readable_fields() -> None:
    info = {
        "account": {
            "email": "person@example.com",
            "organization": "Acme",
            "subscriptionType": "max",
            "apiProvider": "firstParty",
            "displayName": "Pat",
        }
    }

    details = engine_details(info)

    assert details == EngineDetails(
        account=AccountInfo(
            display_name="Pat", email="person@example.com", plan="Claude Max", organization="Acme"
        )
    )


def test_blank_or_odd_account_fields_are_null() -> None:
    info = {"account": {"email": "  ", "organization": 4, "subscriptionType": ""}}

    assert engine_details(info) == EngineDetails(account=AccountInfo())


@pytest.mark.parametrize("info", [None, {}, {"account": "x", "models": []}, {"commands": []}])
def test_nothing_usable_is_none(info: dict[str, Any] | None) -> None:
    assert engine_details(info) is None


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        ("Claude Pro", "Claude Pro"),
        ("claude max", "claude max"),
        ("pro", "Claude Pro"),
        ("max", "Claude Max"),
        ("max_20x", "Claude Max"),
        ("Team", "Claude Team"),
        ("enterprise", "Claude Enterprise"),
        ("free", "Claude Free"),
        ("claude_max", "Claude Max"),
        ("startup-plan", "Startup Plan"),
        ("   ", None),
    ],
)
def test_plan_labels(raw: str, label: str | None) -> None:
    assert plan_label(raw) == label
