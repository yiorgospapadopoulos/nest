from pathlib import Path
from typing import Any

import pytest

from harness.design.errors import DesignError
from harness.design.loader import find_root, load_tokens
from tests.design_support import REPO_ROOT, STATUSES, minimal_tokens, themed, write_tokens


def _load(tmp_path: Path, data: dict[str, Any]) -> None:
    load_tokens(write_tokens(tmp_path, data))


def _rejects(tmp_path: Path, data: dict[str, Any], message: str) -> None:
    with pytest.raises(DesignError, match=message):
        _load(tmp_path, data)


def test_repository_tokens_cover_the_locked_design() -> None:
    tokens = load_tokens(REPO_ROOT / "design" / "tokens.toml")
    assert tuple(tokens.status) == STATUSES
    assert list(tokens.accent.options) == ["graphite", "ocean", "teal", "moss", "clay", "rose"]
    assert tokens.accent.default == "graphite"
    assert list(tokens.wallpaper.options) == ["stone", "sage", "sky", "slate"]
    assert all(len(style.stops) == 3 for style in tokens.wallpaper.options.values())
    assert tokens.status["running"].fill.light == "#0a7aff"
    assert tokens.colors["text"]["primary"].dark == "#f2f3f7"
    assert tokens.glass.blur.heavy == 30
    assert tokens.typography.size["headline"] == 17
    assert tokens.motion.duration["attention"] == 2600


def test_minimal_tokens_load(tmp_path: Path) -> None:
    tokens = load_tokens(write_tokens(tmp_path, minimal_tokens()))
    assert tokens.typography.family["system"] == ["-apple-system", "SF Pro Text"]
    assert tokens.wallpaper.options["stone"].stops[0].center == (12, 18)


def test_a_color_without_a_dark_value_is_rejected(tmp_path: Path) -> None:
    data = minimal_tokens()
    data["colors"]["text"]["primary"] = {"light": "#000000"}
    _rejects(tmp_path, data, r"colors\.text\.primary\.dark: Field required")


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    data = minimal_tokens()
    data["colors"]["text"]["primary"]["mid"] = "#000000"
    _rejects(tmp_path, data, r"colors\.text\.primary\.mid: Extra inputs are not permitted")
    data = minimal_tokens()
    data["shadows"] = {}
    _rejects(tmp_path, data, r"shadows: Extra inputs are not permitted")


def test_invalid_color_strings_are_rejected(tmp_path: Path) -> None:
    data = minimal_tokens()
    data["glass"]["border"] = themed("#000000", "white")
    _rejects(tmp_path, data, r"glass\.border\.dark: Value error, invalid color 'white'")


@pytest.mark.parametrize("name", ["Text", "text-primary", "1st", "text__x", "_text"])
def test_token_names_must_be_snake_case(tmp_path: Path, name: str) -> None:
    data = minimal_tokens()
    data["spacing"][name] = 4
    _rejects(tmp_path, data, "String should match pattern")


def test_status_kinds_are_fixed(tmp_path: Path) -> None:
    data = minimal_tokens()
    del data["status"]["interrupted"]
    _rejects(tmp_path, data, "status must define exactly running, waiting, review")
    data = minimal_tokens()
    data["status"]["paused"] = data["status"]["done"]
    _rejects(tmp_path, data, "status must define exactly")


@pytest.mark.parametrize("section", ["accent", "wallpaper"])
def test_the_default_option_must_exist(tmp_path: Path, section: str) -> None:
    data = minimal_tokens()
    data[section]["default"] = "neon"
    _rejects(tmp_path, data, f"{section}: Value error, default 'neon' is not one of the options")


def test_a_wallpaper_needs_at_least_one_stop(tmp_path: Path) -> None:
    data = minimal_tokens()
    data["wallpaper"]["options"]["stone"]["stops"] = []
    _rejects(tmp_path, data, "stops: List should have at least 1 item")


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("radius", "window", -1),
        ("spacing", "md", -2),
        ("motion", "duration", {"fast": -5}),
        ("motion", "easing", {"pop": [1.2, 0, 0.5, 1]}),
        ("typography", "weight", {"bold": 1001}),
        ("typography", "size", {"body": 0}),
        ("typography", "family", {"system": ['SF "Pro"']}),
        ("typography", "family", {"system": []}),
    ],
)
def test_out_of_range_values_are_rejected(
    tmp_path: Path, section: str, key: str, value: object
) -> None:
    data = minimal_tokens()
    data[section][key] = value
    with pytest.raises(DesignError, match=section):
        _load(tmp_path, data)


def test_invalid_toml_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "tokens.toml"
    path.write_text("colors = [", encoding="utf-8")
    with pytest.raises(DesignError, match="invalid TOML"):
        load_tokens(path)


def test_a_missing_token_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(DesignError, match=r"tokens\.toml: not found"):
        load_tokens(tmp_path / "tokens.toml")


def test_the_root_is_found_by_walking_up(tmp_path: Path) -> None:
    write_tokens(tmp_path, minimal_tokens())
    nested = tmp_path / "daemon" / "src"
    nested.mkdir(parents=True)
    assert find_root(nested) == tmp_path
    assert find_root(tmp_path) == tmp_path


def test_a_missing_root_is_reported(tmp_path: Path) -> None:
    with pytest.raises(DesignError, match=r"could not find design/tokens\.toml"):
        find_root(tmp_path)


def test_repository_glass_themes_are_the_approved_five() -> None:
    themes = load_tokens(REPO_ROOT / "design" / "tokens.toml").glass.themes
    assert themes.default == "clear"
    assert list(themes.options) == ["clear", "frosted", "smoke", "bluegrey", "deep"]
    names = [theme.name for theme in themes.options.values()]
    assert names == ["Clear", "Frosted", "Smoke", "Blue Grey", "Deep"]
    clear, frosted, deep = (themes.options[name] for name in ("clear", "frosted", "deep"))
    assert clear.backdrop.blur == 10
    assert clear.radius.control == 999
    # Frosted keeps Clear's window radius and strip height, and changes its own blur.
    assert frosted.radius.window == 24
    assert frosted.spacing.strip_height == 46
    assert frosted.backdrop.blur == 48
    assert themes.options["smoke"].radius.control == 8
    assert deep.shadow.window_far.y == 70
    assert deep.colors.tint.dark == "rgba(6,10,18,0.72)"


def test_a_theme_inherits_what_it_does_not_override_from_the_default(tmp_path: Path) -> None:
    data = minimal_tokens()
    data["glass"]["themes"]["options"]["deep"]["colors"]["rim"] = {"light": "#123456"}
    themes = load_tokens(write_tokens(tmp_path, data)).glass.themes
    clear, deep = themes.options["clear"], themes.options["deep"]
    assert deep.name == "Deep"
    assert deep.backdrop.blur == 44
    assert deep.backdrop.saturation == clear.backdrop.saturation == 160
    assert deep.radius.window == 28
    assert deep.radius.pane == 18
    assert deep.colors.tint.light == "rgba(160,174,196,0.55)"
    assert deep.colors.surface == clear.colors.surface
    # A color can override one mode and keep the other.
    assert deep.colors.rim.light == "#123456"
    assert deep.colors.rim.dark == clear.colors.rim.dark
    assert deep.shadow.panel.spread == -20
    assert deep.shadow.window_near == clear.shadow.window_near
    assert deep.spacing == clear.spacing


def test_a_theme_needs_its_own_name_and_description(tmp_path: Path) -> None:
    data = minimal_tokens()
    del data["glass"]["themes"]["options"]["deep"]["description"]
    _rejects(tmp_path, data, r"glass\.themes\.options\.deep\.description: Field required")


def test_the_default_theme_must_define_every_value(tmp_path: Path) -> None:
    data = minimal_tokens()
    del data["glass"]["themes"]["options"]["clear"]["colors"]["rim"]
    _rejects(tmp_path, data, r"glass\.themes\.options\.clear\.colors\.rim: Field required")


def test_the_default_theme_must_exist(tmp_path: Path) -> None:
    data = minimal_tokens()
    data["glass"]["themes"]["default"] = "sand"
    _rejects(
        tmp_path, data, r"glass\.themes: Value error, default 'sand' is not one of the options"
    )


def test_a_bad_theme_color_is_rejected(tmp_path: Path) -> None:
    data = minimal_tokens()
    data["glass"]["themes"]["options"]["deep"]["colors"]["tint"]["dark"] = "black"
    _rejects(
        tmp_path,
        data,
        r"glass\.themes\.options\.deep\.colors\.tint\.dark: Value error, invalid color 'black'",
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"radius": {"pane": -1}}, r"deep\.radius\.pane"),
        ({"backdrop": {"blur": -4}}, r"deep\.backdrop\.blur"),
        ({"name": 'Deep "blue"'}, r"deep\.name"),
        ({"description": ""}, r"deep\.description"),
        ({"shadow": {"panel": {"depth": 3}}}, r"deep\.shadow\.panel\.depth: Extra inputs"),
        ({"spacing": {"margin": 3}}, r"deep\.spacing\.margin: Extra inputs"),
    ],
)
def test_invalid_theme_values_are_rejected(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    data = minimal_tokens()
    data["glass"]["themes"]["options"]["deep"].update(change)
    _rejects(tmp_path, data, message)


@pytest.mark.parametrize(
    "themes",
    [
        "clear",
        {"default": "clear", "options": ["clear"]},
        {"default": ["clear"], "options": {"clear": {}}},
        {"default": "clear", "options": {"clear": "glass"}},
    ],
)
def test_malformed_theme_tables_are_rejected(tmp_path: Path, themes: object) -> None:
    data = minimal_tokens()
    data["glass"]["themes"] = themes
    _rejects(tmp_path, data, r"glass\.themes")
