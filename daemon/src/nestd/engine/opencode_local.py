"""Which of OpenCode's models run on the user's own servers.

OpenCode lists whatever its own config adds next to its hosted models, so an LM Studio
server shows up as `lmstudio/<model>`. The clients list those apart from the hosted ones.
"""

import json
import logging
import re
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# OpenCode's own providers for servers on this computer, needing no address in the config.
_BUILT_IN = frozenset({"lmstudio", "ollama"})
_LOOPBACK = frozenset({"localhost", "0.0.0.0", "::1"})  # noqa: S104 - compared, never bound
_CONFIG_FILES = ("opencode.json", "opencode.jsonc")
# Strings are matched first so that a `//` inside a URL stays.
_JSONC = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.DOTALL)
_TRAILING_COMMA = re.compile(r'("(?:\\.|[^"\\])*")|,(\s*[}\]])')


def _plain_json(text: str) -> str:
    text = _JSONC.sub(lambda match: match.group(1) or "", text)
    return _TRAILING_COMMA.sub(lambda match: match.group(1) or match.group(2), text)


def _is_loopback(url: object) -> bool:
    if not isinstance(url, str):
        return False
    host = urlsplit(url).hostname or ""
    return host in _LOOPBACK or host.startswith("127.")


def _configured(path: Path) -> set[str]:
    """The providers in one config file with an address on this computer."""
    try:
        config = json.loads(_plain_json(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return set()
    except (OSError, ValueError) as error:
        logger.warning("could not read %s: %s", path.name, type(error).__name__)
        return set()
    if not isinstance(config, dict):
        return set()
    providers = cast(dict[str, object], config).get("provider")
    if not isinstance(providers, dict):
        return set()
    found: set[str] = set()
    for name, entry in cast(dict[str, object], providers).items():
        options = cast(dict[str, object], entry).get("options") if isinstance(entry, dict) else None
        if isinstance(options, dict) and _is_loopback(
            cast(dict[str, object], options).get("baseURL")
        ):
            found.add(name)
    return found


def local_providers(config_folder: Path) -> frozenset[str]:
    """OpenCode's providers on this computer, by the id its models' values start with."""
    found: set[str] = set(_BUILT_IN)
    for name in _CONFIG_FILES:
        found |= _configured(config_folder / name)
    return frozenset(found)


def is_local_model(value: str, providers: frozenset[str]) -> bool:
    return value.partition("/")[0] in providers
