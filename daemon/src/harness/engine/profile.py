"""The account name Claude Code shows, read from its own `~/.claude.json` (D039).

Claude Code's initialize response carries no display name, so the name is read from the
profile Claude Code keeps. Only `oauthAccount.displayName`, else `oauthAccount.fullName`, is
taken; the rest of the file (which holds other account details) is never kept, logged or
served, and the file is never written.
"""

import json
import logging
from pathlib import Path
from typing import cast

logger = logging.getLogger(__name__)

_NAME_KEYS = ("displayName", "fullName")


def profile_name(path: Path | None) -> str | None:
    """The trimmed profile name; None when there is no file or no usable name."""
    if path is None:
        return None
    try:
        data: object = json.loads(path.read_bytes().decode("utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        # The kind only: the content can hold other account details.
        logger.warning("could not read Claude Code's profile name (%s)", type(error).__name__)
        return None
    account = cast(dict[str, object], data).get("oauthAccount") if isinstance(data, dict) else None
    if not isinstance(account, dict):
        return None
    for key in _NAME_KEYS:
        value = cast(dict[str, object], account).get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
