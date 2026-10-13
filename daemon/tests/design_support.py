"""A small valid token set and helpers for the design generator tests."""

import shutil
from pathlib import Path
from typing import Any

import tomli_w

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUSES = ("running", "waiting", "review", "failed", "done", "interrupted")


def themed(light: str = "#000000", dark: str = "#ffffff") -> dict[str, str]:
    return {"light": light, "dark": dark}


GLASS_COLORS = (
    "tint",
    "surface",
    "surface_subtle",
    "stroke",
    "edge",
    "highlight",
    "rim",
    "shadow_color",
    "strip",
    "shell",
)


def glass_themes() -> dict[str, Any]:
    """A complete base theme and one that overrides a few values."""
    colors = {name: themed("rgba(255,255,255,0.2)", "rgba(24,26,32,0.26)") for name in GLASS_COLORS}
    clear = {
        "name": "Clear",
        "description": "The base layer.",
        "backdrop": {"blur": 10, "saturation": 160},
        "colors": colors,
        "radius": {
            "window": 24,
            "panel": 20,
            "pane": 18,
            "card": 14,
            "item": 10,
            "control": 999,
            "small": 7,
            "tab": 12,
        },
        "spacing": {
            "gap": 10,
            "row_padding_y": 7,
            "transcript_padding_top": 14,
            "transcript_padding_x": 16,
            "transcript_padding_bottom": 10,
            "transcript_gap": 11,
            "strip_height": 46,
            "toolbar_height": 48,
        },
        "shadow": {
            "panel": {"y": 10, "blur": 28, "spread": -16},
            "window_far": {"y": 50, "blur": 100, "spread": -40},
            "window_near": {"y": 18, "blur": 36, "spread": -18},
        },
    }
    deep = {
        "name": "Deep",
        "description": "Thick glass.",
        "backdrop": {"blur": 44},
        "colors": {"tint": themed("rgba(160,174,196,0.55)", "rgba(6,10,18,0.72)")},
        "radius": {"window": 28},
        "shadow": {"panel": {"y": 22, "blur": 50, "spread": -20}},
    }
    return {"default": "clear", "options": {"clear": clear, "deep": deep}}


def minimal_tokens() -> dict[str, Any]:
    return {
        "colors": {
            "text": {
                "primary": themed("#1a1b20", "#f2f3f7"),
                "secondary": themed("rgba(26,27,32,0.68)", "rgba(242,243,247,0.7)"),
            },
        },
        "status": {
            name: {"fill": themed(), "text": themed(), "soft": themed()} for name in STATUSES
        },
        "accent": {
            "default": "graphite",
            "options": {
                "graphite": {
                    "fill": themed("#2b2b2e", "#e6e6e9"),
                    "on": themed("#ffffff", "#141416"),
                },
                "ocean": {"fill": themed("#2c6a9a", "#79b4e3"), "on": themed("#ffffff", "#141416")},
            },
        },
        "glass": {
            "tint": {"regular": themed(), "strong": themed(), "clear": themed()},
            "border": themed(),
            "specular": themed(),
            "outline": themed(),
            "shadow": themed(),
            "blur": {"normal": 20, "heavy": 30},
            "saturation": 185,
            "themes": glass_themes(),
        },
        "wallpaper": {
            "default": "stone",
            "options": {
                "stone": {
                    "base": themed("#ebe6de", "#191713"),
                    "stops": [
                        {
                            "color": themed("#d8cdbd", "#3b342a"),
                            "center": [12, 18],
                            "size": [55, 65],
                            "fade": 70,
                        },
                        {
                            "color": themed("#e4d9c9", "#2c271f"),
                            "center": [88, 10],
                            "size": [50, 60],
                            "fade": 72,
                        },
                    ],
                },
            },
        },
        "radius": {"window": 24, "chip": 7.5},
        "spacing": {"md": 8},
        "typography": {
            "family": {"system": ["-apple-system", "SF Pro Text"]},
            "size": {"body": 13},
            "weight": {"bold": 700},
            "line_height": {"body": 1.4},
        },
        "motion": {"duration": {"fast": 200}, "easing": {"pop": [0.2, 0.9, 0.3, 1.15]}},
    }


def write_tokens(root: Path, data: dict[str, Any]) -> Path:
    path = root / "design" / "tokens.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(data), encoding="utf-8")
    return path


def write_mascots(root: Path) -> Path:
    """Copy the shipped mascot sprites into a scratch repository."""
    path = root / "design" / "mascots.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO_ROOT / "design" / "mascots.toml", path)
    return path
