"""B94: the defaults Nest picks when nothing is chosen are real models, levels and modes."""

import pytest

from nestd.engine.models import ModelList, closest_effort, engine_default, listed_models
from nestd.providers.base import ModelOption

LEVELS = ["low", "medium", "high", "xhigh", "max"]


def option(value: str, resolved: str | None = None, levels: list[str] | None = None) -> ModelOption:
    return ModelOption(
        value=value,
        display_name=value.capitalize(),
        description="",
        effort_levels=LEVELS if levels is None else levels,
        resolved_model=resolved,
    )


@pytest.mark.parametrize(
    ("levels", "expected"),
    [
        (LEVELS, "medium"),
        (["low", "high", "max"], "low"),
        (["high", "max"], "high"),
        (["xhigh", "max"], "xhigh"),
        (["low"], "low"),
        (["max", "low"], "low"),
        ([], None),
        (["ultra"], None),
    ],
)
def test_thinking_is_medium_or_the_closest_level_the_model_takes(
    levels: list[str], expected: str | None
) -> None:
    assert closest_effort(levels) == expected


def test_the_engines_default_is_the_listed_model_its_default_entry_resolves_to() -> None:
    models = [
        option("default", resolved="claude-opus-5-5"),
        option("sonnet", resolved="claude-sonnet-5-5"),
        option("opus", resolved="claude-opus-5-5"),
        option("claude-opus-5-5", resolved="claude-opus-5-5"),
    ]

    assert engine_default(models) == "claude-opus-5-5"
    assert engine_default(models[:3]) == "opus"


def test_a_default_resolving_to_an_unlisted_model_names_that_model() -> None:
    assert engine_default([option("default", resolved="gpt-7"), option("gpt-6")]) == "gpt-7"


def test_without_a_resolved_default_the_first_real_model_is_the_default() -> None:
    assert engine_default([option("default"), option("opus"), option("haiku")]) == "opus"
    assert engine_default([option("sonnet"), option("haiku")]) == "sonnet"
    assert engine_default([option("default")]) is None
    assert engine_default([]) is None


def test_menus_list_only_real_models_and_name_the_default() -> None:
    listed = ModelList(
        models=[option("default", resolved="claude-opus-5-5"), option("opus", "claude-opus-5-5")],
        updated_at=None,
    )

    served = listed_models(listed)

    assert [model.value for model in served.models] == ["opus"]
    assert served.default_model == "opus"
    assert listed.models[0].value == "default"
