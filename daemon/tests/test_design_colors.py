import pytest

from harness.design.colors import RGBA, parse_color


def test_hex_colors_parse_to_unit_channels() -> None:
    assert parse_color("#ff8000") == RGBA(red=1.0, green=128 / 255, blue=0.0, alpha=1.0)
    assert parse_color("#FF8000") == parse_color("#ff8000")


def test_rgba_colors_parse_with_their_alpha() -> None:
    assert parse_color("rgba(10,122,255,0.45)") == RGBA(10 / 255, 122 / 255, 1.0, 0.45)
    assert parse_color("rgba( 0, 0, 0, .5 )") == RGBA(0.0, 0.0, 0.0, 0.5)
    assert parse_color("rgba(255,255,255,1)") == RGBA(1.0, 1.0, 1.0, 1.0)


@pytest.mark.parametrize(
    "text",
    [
        "#fff",
        "#gggggg",
        "#ff800080",
        " #ff8000",
        "red",
        "rgb(0,0,0)",
        "rgba(0,0,0)",
        "rgba(256,0,0,1)",
        "rgba(0,0,0,1.5)",
        "rgba(0,0,0,-1)",
    ],
)
def test_other_color_forms_are_rejected(text: str) -> None:
    with pytest.raises(ValueError, match=r"use #rrggbb or rgba\(r,g,b,a\)"):
        parse_color(text)
