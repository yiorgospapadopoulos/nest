"""Typed models for `design/tokens.toml`."""

from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from harness.design.colors import parse_color

STATUSES = ("running", "waiting", "review", "failed", "done", "interrupted")

# snake_case, so names map cleanly to kebab-case CSS variables and camelCase Swift members.
Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")]
Points = Annotated[float, Field(ge=0)]
Percent = Annotated[float, Field(ge=0, le=100)]
FontFamily = Annotated[str, StringConstraints(pattern=r'^[^"\\]+$')]
Unit = Annotated[float, Field(ge=0, le=1)]


def _check_color(text: str) -> str:
    parse_color(text)
    return text


Color = Annotated[str, AfterValidator(_check_color)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ThemedColor(_Strict):
    light: Color
    dark: Color


class StatusColors(_Strict):
    fill: ThemedColor
    text: ThemedColor
    soft: ThemedColor


class AccentColor(_Strict):
    fill: ThemedColor
    on: ThemedColor


class WallpaperStop(_Strict):
    color: ThemedColor
    center: tuple[Percent, Percent]
    size: tuple[Percent, Percent]
    fade: Percent


class WallpaperStyle(_Strict):
    base: ThemedColor
    stops: list[WallpaperStop] = Field(min_length=1)


class _Choice[T](_Strict):
    default: Name
    options: dict[Name, T]

    @model_validator(mode="after")
    def _default_is_an_option(self) -> "_Choice[T]":
        if self.default not in self.options:
            msg = f"default {self.default!r} is not one of the options"
            raise ValueError(msg)
        return self


class Accents(_Choice[AccentColor]):
    pass


class Wallpapers(_Choice[WallpaperStyle]):
    pass


class GlassTint(_Strict):
    regular: ThemedColor
    strong: ThemedColor
    clear: ThemedColor


class GlassBlur(_Strict):
    normal: Points
    heavy: Points


class Glass(_Strict):
    tint: GlassTint
    border: ThemedColor
    specular: ThemedColor
    outline: ThemedColor
    shadow: ThemedColor
    blur: GlassBlur
    saturation: Annotated[float, Field(ge=0)]


class Typography(_Strict):
    family: dict[Name, Annotated[list[FontFamily], Field(min_length=1)]]
    size: dict[Name, Annotated[float, Field(gt=0)]]
    weight: dict[Name, Annotated[int, Field(ge=1, le=1000)]]
    line_height: dict[Name, Annotated[float, Field(gt=0)]]


class Motion(_Strict):
    duration: dict[Name, Annotated[int, Field(ge=0)]]
    easing: dict[Name, tuple[Unit, float, Unit, float]]


class Tokens(_Strict):
    colors: dict[Name, dict[Name, ThemedColor]]
    status: dict[Name, StatusColors]
    accent: Accents
    glass: Glass
    wallpaper: Wallpapers
    radius: dict[Name, Points]
    spacing: dict[Name, Points]
    typography: Typography
    motion: Motion

    @field_validator("status")
    @classmethod
    def _status_kinds_are_fixed(cls, status: dict[str, StatusColors]) -> dict[str, StatusColors]:
        if set(status) != set(STATUSES):
            msg = f"status must define exactly {', '.join(STATUSES)}"
            raise ValueError(msg)
        return status
