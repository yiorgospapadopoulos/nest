"""A pixie's slug is its `@` handle and its subagent name, so it must be safe and unique."""

import re
import unicodedata

from harness.pixies.errors import InvalidSlugError

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
# Claude Code's own agents; a pixie with one of these names would shadow it.
RESERVED_SLUGS = frozenset(
    {"general-purpose", "explore", "plan", "statusline-setup", "claude-code-guide"}
)
FALLBACK = "pixie"


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:32].rstrip("-")
    return slug or FALLBACK


def check_slug(slug: str) -> None:
    if not SLUG.match(slug):
        msg = f"invalid slug {slug!r}: use 1 to 32 lowercase letters, digits and dashes"
        raise InvalidSlugError(msg)
    if slug in RESERVED_SLUGS:
        msg = f"{slug!r} is the name of a Claude Code agent"
        raise InvalidSlugError(msg)
