"""What an agent's content must look like for each ready-made kind (B88): slides split on a
line that is exactly `---`, designs and design systems as JSON with clear messages that
name the bad field.
"""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from nestd.artifacts.kinds import (
    COMPONENT_HTML_MAX,
    SCREEN_HTML_MAX,
    SLIDES_MAX,
    Design,
    DesignSystem,
    _problems,  # pyright: ignore[reportPrivateUsage]
    checked_kind_content,
    slides_of,
)
from nestd.artifacts.models import InvalidArtifactError

SCREEN: dict[str, Any] = {
    "label": "A",
    "title": "Start screen",
    "device": "phone",
    "html": "<style>:root{--a:1}</style><main>Hi</main>",
}
SYSTEM: dict[str, Any] = {
    "name": "Nest",
    "description": "Calm and quiet.",
    "colors": [
        {"name": "accent", "light": "#4C6EF5", "dark": "#7B93FF", "role": "Buttons"},
        {"name": "background", "light": "#fff"},
        {"name": "veil", "light": "#00000080"},
    ],
    "typography": [
        {
            "name": "Title",
            "family": "-apple-system, sans-serif",
            "size": 28,
            "weight": 700,
            "line_height": 1.2,
            "sample": "Good morning",
        }
    ],
    "spacing": [{"name": "s", "value": 8}],
    "radii": [{"name": "card", "value": 16}],
    "components": [{"name": "Primary button", "html": "<button>Go</button>"}],
}


def problem(kind: str, content: str) -> str:
    with pytest.raises(InvalidArtifactError) as refusal:
        checked_kind_content(kind, content)  # type: ignore[arg-type]
    return str(refusal.value)


def design(**changes: object) -> str:
    return json.dumps({"screens": [SCREEN], **changes})


def system(**changes: object) -> str:
    return json.dumps({**SYSTEM, **changes})


@pytest.mark.parametrize("kind", ["markdown", "html", "document"])
def test_free_text_kinds_take_any_content(kind: str) -> None:
    checked_kind_content(kind, "---\n\n---")  # type: ignore[arg-type]


def test_slides_split_on_lines_that_are_exactly_three_dashes() -> None:
    deck = "# One\n\n| a |\n|---|\n| b |\n---\n## Two\n--- \n----\n---\r\nThree"

    assert slides_of(deck) == ["# One\n\n| a |\n|---|\n| b |", "## Two\n--- \n----", "Three"]
    checked_kind_content("slides", deck)


@pytest.mark.parametrize(
    ("deck", "message"),
    [
        ("---\n# Two", "slide 1 is empty"),
        ("# One\n---\n  \n---\n# Three", "slide 2 is empty"),
        ("# One\n---", "slide 2 is empty"),
    ],
)
def test_empty_slides_are_refused(deck: str, message: str) -> None:
    assert problem("slides", deck) == (
        f"{message}; slides are separated by a line that is exactly ---, and each needs content"
    )


def test_a_deck_has_at_most_200_slides() -> None:
    checked_kind_content("slides", "\n---\n".join(["x"] * SLIDES_MAX))

    assert problem("slides", "\n---\n".join(["x"] * (SLIDES_MAX + 1))) == (
        f"the deck has {SLIDES_MAX + 1} slides; it may have at most {SLIDES_MAX}"
    )


def test_a_design_is_parsed_with_its_intro_layout_and_screens() -> None:
    full = {
        **SCREEN,
        "description": "Calm: one action per screen.",
        "device": "desktop",
        "frame": "browser",
        "url": "nest.app/settings",
    }
    parsed = Design.model_validate_json(design(intro="Two ideas", layout="grid", screens=[full]))
    bare = Design.model_validate_json(design())

    assert (parsed.intro, parsed.layout) == ("Two ideas", "grid")
    screen = parsed.screens[0]
    assert (screen.label, screen.description, screen.device) == (
        "A",
        "Calm: one action per screen.",
        "desktop",
    )
    assert (screen.frame, screen.url) == ("browser", "nest.app/settings")
    assert (bare.intro, bare.layout) == (None, "stack")
    assert (bare.screens[0].frame, bare.screens[0].description, bare.screens[0].url) == (
        "auto",
        None,
        None,
    )
    checked_kind_content("design", design())


def test_the_older_names_notes_and_variant_still_work() -> None:
    older = {k: v for k, v in SCREEN.items() if k != "label"} | {"variant": "B2"}

    parsed = Design.model_validate_json(json.dumps({"notes": "Why", "screens": [older]}))

    assert (parsed.intro, parsed.screens[0].label) == ("Why", "B2")


@pytest.mark.parametrize("device", ["phone", "tablet", "desktop", "square"])
@pytest.mark.parametrize("frame", ["auto", "browser", "window", "phone", "tablet", "none"])
@pytest.mark.parametrize("layout", ["stack", "grid", "tabs", "canvas"])
def test_every_device_frame_and_layout_is_accepted(device: str, frame: str, layout: str) -> None:
    checked_kind_content(
        "design", design(layout=layout, screens=[{**SCREEN, "device": device, "frame": frame}])
    )


def test_texts_of_exactly_their_limits_are_accepted() -> None:
    screen = {**SCREEN, "label": "ABC", "description": "d" * 600, "url": "u" * 200}

    checked_kind_content("design", design(intro="i" * 4000, screens=[screen]))


def test_a_screen_html_of_exactly_the_limit_is_accepted() -> None:
    html = "a" * SCREEN_HTML_MAX

    checked_kind_content("design", design(screens=[{**SCREEN, "html": html}]))


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{", "the content of a design must be JSON"),
        ("[1]", "the content of a design must be a JSON object"),
        (json.dumps({"screens": []}), "screens needs at least 1 item"),
        (json.dumps({"screens": [SCREEN] * 25}), "screens has at most 24 items"),
        (json.dumps({"intro": "x"}), "screens is required"),
        (
            design(screens=[SCREEN, SCREEN, {**SCREEN, "device": "watch"}]),
            "screens[2].device must be phone, tablet, desktop or square",
        ),
        (
            design(screens=[{**SCREEN, "frame": "bezel"}]),
            "screens[0].frame must be auto, browser, window, phone, tablet or none",
        ),
        (design(layout="list"), "layout must be stack, grid, tabs or canvas"),
        (design(screens=[{**SCREEN, "label": "ABCD"}]), "screens[0].label must be 1 to 3"),
        (design(screens=[{**SCREEN, "label": "A!"}]), "screens[0].label must be 1 to 3"),
        (design(screens=[{**SCREEN, "label": ""}]), "screens[0].label must be 1 to 3"),
        (
            design(screens=[{k: v for k, v in SCREEN.items() if k != "label"}]),
            "screens[0].label is required",
        ),
        (design(intro="i" * 4001), "intro has at most 4000 characters"),
        (design(screens=[{**SCREEN, "description": "d" * 601}]), "has at most 600 characters"),
        (design(screens=[{**SCREEN, "url": "u" * 201}]), "screens[0].url has at most 200"),
        (design(screens=[{**SCREEN, "title": "T" * 81}]), "screens[0].title has at most 80"),
        (design(screens=[{**SCREEN, "title": " "}]), "screens[0].title needs text"),
        (design(screens=[{**SCREEN, "html": 5}]), "screens[0].html must be a string"),
        (
            design(screens=[{**SCREEN, "html": "é" * (SCREEN_HTML_MAX // 2 + 1)}]),
            f"screens[0].html is {SCREEN_HTML_MAX + 2} bytes; at most {SCREEN_HTML_MAX}",
        ),
        (design(screens=[{**SCREEN, "colour": "red"}]), "screens[0].colour is not a known field"),
        (design(intro=3), "intro must be a string"),
        (design(screens=["Start screen"]), "screens[0] must be an object"),
    ],
)
def test_bad_designs_are_refused_naming_the_field(content: str, message: str) -> None:
    assert message in problem("design", content)


def test_a_design_system_is_parsed() -> None:
    parsed = DesignSystem.model_validate_json(system())
    bare = DesignSystem.model_validate_json(
        json.dumps({"name": "Bare", "colors": [{"name": "ink", "light": "#000"}]})
    )

    assert parsed.colors[0].dark == "#7B93FF"
    assert parsed.typography[0].line_height == 1.2
    assert (bare.typography, bare.spacing, bare.radii, bare.components) == ([], [], [], [])
    assert (bare.description, bare.colors[0].dark, bare.colors[0].role) == (None, None, None)
    checked_kind_content("design_system", system())


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("nope", "the content of a design system must be JSON"),
        (system(colors=[]), "colors needs at least 1 item"),
        (system(colors=[{"name": "c", "light": "#000"}] * 201), "colors has at most 200 items"),
        (system(spacing=[{"name": "s", "value": 1}] * 101), "spacing has at most 100 items"),
        (system(name=""), "name needs text"),
        (
            system(colors=[{"name": "c", "light": "blue"}]),
            "colors[0].light must be a hex colour such as #4C6EF5 (#rgb, #rrggbb or #rrggbbaa)",
        ),
        (system(colors=[{"name": "c", "light": "#000", "dark": "#12345"}]), "colors[0].dark must"),
        (system(colors=[{"name": "c"}]), "colors[0].light is required"),
        (
            system(typography=[{**SYSTEM["typography"][0], "size": 0}]),
            "typography[0].size must be greater than 0",
        ),
        (
            system(typography=[{**SYSTEM["typography"][0], "weight": "bold"}]),
            "typography[0].weight must be an integer",
        ),
        (
            system(typography=[{**SYSTEM["typography"][0], "weight": 1001}]),
            "typography[0].weight must be at most 1000",
        ),
        (system(radii=[{"name": "r", "value": -1}]), "radii[0].value must be at least 0"),
        (
            system(components=[{"name": "c", "html": "a" * (COMPONENT_HTML_MAX + 1)}]),
            f"components[0].html is {COMPONENT_HTML_MAX + 1} bytes; at most {COMPONENT_HTML_MAX}",
        ),
        (system(colors="red"), "colors must be a list"),
        (system(spacing=[{"name": "s", "value": "8px"}]), "spacing[0].value must be a number"),
    ],
)
def test_bad_design_systems_are_refused_naming_the_field(content: str, message: str) -> None:
    assert message in problem("design_system", content)


def test_several_problems_are_listed_together() -> None:
    content = design(screens=[{**SCREEN, "device": "watch", "label": "ABCD"}])

    message = problem("design", content)

    assert message.startswith("the design is not valid: ")
    assert "screens[0].device must be" in message
    assert "screens[0].label must be" in message


def test_an_unforeseen_problem_keeps_pydantics_words() -> None:
    error = ValidationError.from_exception_data(
        "Design", [{"type": "uuid_type", "loc": ("screens", 0, "id"), "input": 1}]
    )

    assert _problems(error, "design") == (
        "the design is not valid: screens[0].id UUID input should be a string, bytes or UUID object"
    )


def test_html_sent_as_a_design_is_refused_with_the_shape_to_send() -> None:
    message = problem("design", "<!doctype html><main>Settings</main>")

    assert message == (
        "the content of a design must be JSON, not HTML: "
        '{"intro": "What is being decided", "layout": "stack", "screens": [{"label": "A",'
        ' "title": "Settings", "description": "The idea and its trade-off", "device": "phone",'
        ' "frame": "auto", "html": "<style>...</style><main>...</main>"}]}; put each option\'s'
        " HTML in a screen's html (the JSON parser said: expected value at line 1 column 1)"
    )


def test_html_sent_as_a_design_system_is_refused_with_the_shape_to_send() -> None:
    message = problem("design_system", "<html><body>Tokens</body></html>")

    assert message == (
        "the content of a design system must be JSON, not HTML: "
        '{"name": "...", "colors": [{"name": "accent", "light": "#4C6EF5", "dark": "#7B93FF"}],'
        ' "typography": [{"name": "Title", "family": "-apple-system, sans-serif", "size": 28,'
        ' "weight": 700, "line_height": 1.2}], "spacing": [{"name": "s", "value": 8}],'
        ' "radii": [{"name": "card", "value": 16}], "components": [{"name": "Primary button",'
        ' "html": "<style>...</style><button>...</button>"}]}; put each component\'s HTML in'
        " a component's html (the JSON parser said: expected value at line 1 column 1)"
    )
