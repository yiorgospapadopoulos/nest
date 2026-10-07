"""The `origin` push URL that the daemon publishes to (D050)."""

import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from harness.gitops.runner import CommandError, CommandRunner

REMOTE = "origin"
GITHUB_HOST = "github.com"
# scp-like syntax: `[user@]host:path`.
_SCP = re.compile(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>[^/].*)$")


async def push_urls(cwd: Path, run: CommandRunner) -> list[str]:
    """Where `git push origin` sends commits, after git's own URL rewriting; [] without
    an `origin`. Credentials in http(s) URLs are left out.
    """
    try:
        output = await run(["git", "remote", "get-url", "--push", "--all", REMOTE], cwd)
    except CommandError:
        return []
    return [scrub_url(line) for line in output.splitlines() if line]


def scrub_url(url: str) -> str:
    """The URL without a user name or token in an http(s) URL."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))


def github_repo(url: str) -> str | None:
    """`owner/name` for a github.com URL, else None."""
    if "://" in url:
        parts = urlsplit(url)
        host, path = parts.hostname, parts.path
    elif match := _SCP.match(url):
        host, path = match["host"].lower(), match["path"]
    else:
        return None
    if host != GITHUB_HOST:
        return None
    segments = path.strip("/").removesuffix(".git").split("/")
    if len(segments) != 2 or not all(segments):
        return None
    return "/".join(segments)
