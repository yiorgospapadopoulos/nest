"""A small valid token set and helpers for the design generator tests."""

from pathlib import Path
from typing import Any

import tomli_w

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUSES = ("running", "waiting", "review", "failed", "done", "interrupted")


def themed(light: str = "#000000", dark: str = "#ffffff") -> dict[str, str]:
    return {"light": light, "dark": dark}


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
