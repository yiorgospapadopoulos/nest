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
    assert tokens.radius["window"] == 24
    assert tokens.motion.easing["pop"] == (0.2, 0.9, 0.3, 1.15)


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
