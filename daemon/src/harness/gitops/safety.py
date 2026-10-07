"""Git run by the daemon, with the user's credentials, in a tree the agent could change (D050).

An agent can write `.git/config`, `.git/hooks` and `.gitattributes`. The daemon's approved
commit, push and pull request, and the diffs they are based on, therefore run with:
- `HARDENED` overrides on every git command: no hooks, no fsmonitor program, no `ext::`
  transport;
- a check of the repository's own settings (local and worktree config, with the files they
  include) for anything else that runs a program or sends data elsewhere (`UNSAFE_REASONS`);
  publishing refuses them, and diffs neutralize filter drivers instead.
"""

import re
from dataclasses import dataclass

GIT_CONFIG_LIST = ("git", "config", "--list", "--show-scope", "-z")
# `-c` settings come after every config file, so they win over the repository's own.
HARDENED = (
    *("-c", "core.hooksPath=/dev/null"),
    *("-c", "core.fsmonitor=false"),
    *("-c", "protocol.ext.allow=never"),
)
_REPO_SCOPES = frozenset({"local", "worktree"})
_BOOLEANS = frozenset({"true", "false", "yes", "no", "on", "off", "1", "0", ""})
# Transfer tuning that sends nothing elsewhere and runs nothing.
_SAFE_HTTP = frozenset({"postbuffer", "lowspeedlimit", "lowspeedtime", "version", "maxrequests"})
# What `git lfs install --local` writes: the user's own git-lfs from the daemon's PATH.
_LFS_VALUES = {
    "filter.lfs.clean": "git-lfs clean -- %f",
    "filter.lfs.smudge": "git-lfs smudge -- %f",
    "filter.lfs.process": "git-lfs filter-process",
}
UNSAFE_REASONS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), reason)
    for pattern, reason in (
        (r"core\.(?:sshcommand|gitproxy|askpass|alternaterefscommand)$", "runs a program"),
        (r"ssh\.variant$", "changes how ssh runs"),
        (r"credential\.", "handles your credentials"),
        (r"url\..*\.(?:insteadof|pushinsteadof)$", "rewrites remote URLs"),
        (r"http\.", "changes where or how data is sent"),
        (r"remote\..*\.(?:receivepack|uploadpack|proxy|vcs)$", "runs a program"),
        (r"filter\.", "runs a program on your files"),
        (r"gpg\.", "runs a program"),
        (r"hook\.", "runs a program"),
        (r"protocol\.", "allows other transports"),
        (r"core\.fsmonitor$", "runs a program"),
        (r"diff\.external$", "runs a program"),
        (r"diff\..*\.(?:command|textconv)$", "runs a program"),
        (r"merge\..*\.driver$", "runs a program"),
        (r"(?:core|sequence)\.editor$", "runs a program"),
        (r"core\.pager$", "runs a program"),
        (r"pager\.", "runs a program"),
        (r"interactive\.difffilter$", "runs a program"),
    )
)


@dataclass(frozen=True)
class RepoSetting:
    scope: str
    key: str
    value: str


def repo_settings(listing: str) -> list[RepoSetting]:
    """The repository's own settings from `GIT_CONFIG_LIST` output."""
    fields = listing.split("\0")
    settings: list[RepoSetting] = []
    for scope, entry in zip(fields[::2], fields[1::2], strict=False):
        key, _, value = entry.partition("\n")
        if scope in _REPO_SCOPES:
            settings.append(RepoSetting(scope, key, value))
    return settings


def unsafe_settings(settings: list[RepoSetting]) -> list[str]:
    """`key (reason)` for each setting that would run a program or send data elsewhere."""
    found: list[str] = []
    for setting in settings:
        reason = _unsafe_reason(setting.key.lower(), setting.value)
        if reason is not None and f"{setting.key} ({reason})" not in found:
            found.append(f"{setting.key} ({reason})")
    return found


def _unsafe_reason(key: str, value: str) -> str | None:
    if key.startswith("http.") and key.rsplit(".", 1)[-1] in _SAFE_HTTP:
        return None
    if key == "protocol.version" or (key == "core.fsmonitor" and value.lower() in _BOOLEANS):
        return None
    if key.startswith("filter.") and (key.endswith(".required") or _LFS_VALUES.get(key) == value):
        return None
    for pattern, reason in UNSAFE_REASONS:
        if pattern.match(key):
            return reason
    return None


def filter_overrides(settings: list[RepoSetting]) -> list[str]:
    """`-c` options that switch off the repository's own filter drivers.

    Raises ValueError for a driver name `-c` cannot express (it splits at the first `=`).
    """
    drivers: list[str] = []
    for setting in settings:
        if setting.key.lower().startswith("filter.") and setting.key.count(".") >= 2:
            driver = setting.key[len("filter.") : setting.key.rindex(".")]
            if "=" in driver:
                msg = f"filter driver {driver!r} cannot be switched off"
                raise ValueError(msg)
            if driver not in drivers:
                drivers.append(driver)
    options: list[str] = []
    for driver in drivers:
        for name, value in (("clean", ""), ("smudge", ""), ("process", ""), ("required", "false")):
            options.extend(("-c", f"filter.{driver}.{name}={value}"))
    return options
