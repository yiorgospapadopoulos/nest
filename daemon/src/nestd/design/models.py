"""Typed models for `design/tokens.toml`."""

from collections.abc import Mapping
from typing import Annotated, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from nestd.design.colors import parse_color

STATUSES = ("running", "waiting", "review", "failed", "done", "interrupted")

# snake_case, so names map cleanly to kebab-case CSS variables and camelCase Swift members.
Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")]
Points = Annotated[float, Field(ge=0)]
Percent = Annotated[float, Field(ge=0, le=100)]
FontFamily = Annotated[str, StringConstraints(pattern=r'^[^"\\]+$')]
Unit = Annotated[float, Field(ge=0, le=1)]
# Shown to people and quoted in Swift string literals.
Label = Annotated[str, StringConstraints(pattern=r'^[^"\\\n]+$')]


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


def _not_an_option(default: str) -> str:
    return f"default {default!r} is not one of the options"


class _Choice[T](_Strict):
    default: Name
    options: dict[Name, T]

    @model_validator(mode="after")
    def _default_is_an_option(self) -> "_Choice[T]":
        if self.default not in self.options:
            raise ValueError(_not_an_option(self.default))
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


class GlassBackdrop(_Strict):
    """What shows through the glass: blur radius in points, saturation in percent."""

    blur: Points
    saturation: Annotated[float, Field(ge=0)]


class GlassColors(_Strict):
    tint: ThemedColor
    surface: ThemedColor
    surface_subtle: ThemedColor
    stroke: ThemedColor
    edge: ThemedColor
    highlight: ThemedColor
    rim: ThemedColor
    shadow_color: ThemedColor
    strip: ThemedColor
    shell: ThemedColor


class GlassRadius(_Strict):
    window: Points
    panel: Points
    pane: Points
    card: Points
    item: Points
    control: Points
    small: Points
    tab: Points


class GlassSpacing(_Strict):
    gap: Points
    row_padding_y: Points
    transcript_padding_top: Points
    transcript_padding_x: Points
    transcript_padding_bottom: Points
    transcript_gap: Points
    strip_height: Points
    toolbar_height: Points


class GlassShadow(_Strict):
    """A drop shadow below the glass: offset, blur and spread in points."""

    y: float
    blur: Points
    spread: float


class GlassShadows(_Strict):
    panel: GlassShadow
    # The window casts two layered shadows.
    window_far: GlassShadow
    window_near: GlassShadow


class GlassStyle(_Strict):
    name: Label
    description: Label
    backdrop: GlassBackdrop
    colors: GlassColors
    radius: GlassRadius
    spacing: GlassSpacing
    shadow: GlassShadows


# Each theme has its own; everything else is inherited from the default theme.
_OWN_KEYS = ("name", "description")


def _merge(base: Mapping[str, object], override: Mapping[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _merge(cast(dict[str, object], current), cast(dict[str, object], value))
        else:
            merged[key] = value
    return merged


class GlassThemes(_Choice[GlassStyle]):
    """The default theme defines every value; the others override only what they change."""

    @model_validator(mode="before")
    @classmethod
    def _inherit_from_default(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        table = cast(dict[str, object], data)
        options, default = table.get("options"), table.get("default")
        if not isinstance(options, dict) or not isinstance(default, str):
            return table
        themes = cast(dict[str, object], options)
        if default not in themes:
            # Checked first: without a base every theme would also miss its inherited values.
            raise ValueError(_not_an_option(default))
        base = themes[default]
        if not isinstance(base, dict):
            return table
        inherited = {
            key: value
            for key, value in cast(dict[str, object], base).items()
            if key not in _OWN_KEYS
        }
        merged = {
            name: _merge(inherited, cast(dict[str, object], theme))
            if isinstance(theme, dict)
            else theme
            for name, theme in themes.items()
        }
        return {**table, "options": merged}


class Glass(_Strict):
    tint: GlassTint
    border: ThemedColor
    specular: ThemedColor
    outline: ThemedColor
    shadow: ThemedColor
    blur: GlassBlur
    saturation: Annotated[float, Field(ge=0)]
    themes: GlassThemes


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
