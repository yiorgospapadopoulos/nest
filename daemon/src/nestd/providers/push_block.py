"""What stops pushes and pull request writes that no command check sees (D013, D160).

The command checks (`git_guard`, each engine's approvals) read the commands an agent runs,
not what a script it wrote runs later. So a guarded run (`SessionSpec.guard_git`) also
gets, in its environment (`push_block`):

- git config that makes every push fail while fetch and pull work. An empty
  `pushInsteadOf` sends the pushes to any URL to an address no helper answers. git does not
  rewrite a remote's own `pushurl` that way, and the user's own longer `pushInsteadOf`
  rule wins over Nest's, so each remote of the run's folders that git says still pushes
  somewhere real has its push addresses replaced by that address too, by name. Only those:
  a remote named for every repository would show in one without it with only a push
  address, which breaks `git fetch --all` there. Remotes are read when the run opens.
- Nest's `gh` first on PATH, which refuses what `is_git_write` flags (pull requests,
  `gh api` writes, `gh auth token`) and any word that is not one of gh's own commands (an
  alias or extension could run anything), and runs the user's own `gh` for the rest.

Left open: a program that runs gh by its full path, a remote added during the run with a
push address of its own, and a program that talks to GitHub with a token it already holds.
An engine whose shell rebuilds PATH puts the user's `gh` back in front where their shell
setup adds its folder: Grok Build's login shell does (`/opt/homebrew/bin`), and Copilot's
puts `/usr/local/bin` first (found by B153's check). A command they run is still judged by
its text; only what a script of theirs runs reaches the user's `gh`.

A normal chat's subagents share its process, so this cannot single them out. On Codex its
own PreToolUse hook does (`subagent_hook_args`), as Nest's hook does on Claude: only a
subagent's events name an `agent_id`, and only those reach the check.
"""

import asyncio
import atexit
import functools
import hashlib
import json
import os
import shlex
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from nestd.gitops.runner import GitError, run_git
from nestd.providers.push_check import DENY

PUSH_OFF_URL = "nest-pushing-is-off://"
_EVERY_URL = (f"url.{PUSH_OFF_URL}.pushInsteadOf", "")
# git config entries, as `GIT_CONFIG_COUNT` and its keys give them.
type GitConfig = Sequence[tuple[str, str]]

GH = "gh"
CODEX_HOOK = "codex-subagent-hook"
GROK_HOOK = "grok-guarded-hook"
_REMOTE_TIME_LIMIT = 10.0
# What Codex calls hooks set with `-c`, and how long one may take (B127).
_SESSION_HOOK_KEY = "/<session-flags>/config.toml:pre_tool_use:0:0"
_HOOK_TIMEOUT = 60


def git_config_env(entries: GitConfig) -> dict[str, str]:
    env = {"GIT_CONFIG_COUNT": str(len(entries))}
    for index, (key, value) in enumerate(entries):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


# The block for every URL alone, as a run's before its remotes are read.
NO_PUSH_ENV = git_config_env([_EVERY_URL])


@dataclass(frozen=True)
class PushBlock:
    git_env: Mapping[str, str]
    bin_dir: Path

    def env(self, path: str | None) -> dict[str, str]:
        """The run's additions: the git config, and `path` with Nest's `gh` first."""
        return {**self.git_env, "PATH": os.pathsep.join(p for p in (str(self.bin_dir), path) if p)}


async def push_block(folders: Iterable[Path]) -> PushBlock:
    """The block for a guarded run working in `folders`."""
    entries: list[tuple[str, str]] = [_EVERY_URL]
    for name in await _still_pushing(dict.fromkeys(folders)):
        entries += [(f"remote.{name}.pushurl", ""), (f"remote.{name}.pushurl", PUSH_OFF_URL)]
    return PushBlock(git_config_env(entries), await asyncio.to_thread(helpers))


async def _still_pushing(folders: Iterable[Path]) -> list[str]:
    """The remotes of `folders` that git, with the block for every URL, still pushes to a
    real address: one with its own `pushurl`, or one the user's own rule rewrites.
    """
    names: dict[str, None] = {}
    for folder in folders:
        try:
            listed = await _git(folder, "remote")
            for name in listed.split():
                if name in names:
                    continue
                urls = await _git(folder, "remote", "get-url", "--push", "--all", name)
                if any(not url.startswith(PUSH_OFF_URL) for url in urls.splitlines()):
                    names[name] = None
        except GitError:  # not a repository, or git is missing
            continue
    return list(names)


async def _git(folder: Path, *args: str) -> str:
    return await run_git(args, folder, _REMOTE_TIME_LIMIT, env=NO_PUSH_ENV)


def subagent_hook_args(bin_dir: Path) -> tuple[str, ...]:
    """`codex app-server` arguments for Codex's own PreToolUse hook that refuses what a
    subagent's tool call pushes (B127), trusted for this run only.
    """
    command = shlex.quote(str(bin_dir / CODEX_HOOK))
    hooks = f'[{{hooks=[{{type="command",command={_toml(command)},timeout={_HOOK_TIMEOUT}}}]}}]'
    digest = codex_hook_hash(command, _HOOK_TIMEOUT)
    state = f"{{{_toml(_SESSION_HOOK_KEY)}={{trusted_hash={_toml(digest)}}}}}"
    return ("-c", f"hooks.PreToolUse={hooks}", "-c", f"hooks.state={state}")


def codex_hook_hash(command: str, timeout: int) -> str:
    """The hash by which Codex trusts a PreToolUse command hook with no matcher: sha256 of
    its definition as JSON with sorted keys (Codex 0.163.0's `version_for_toml`, checked
    against its `hooks/list`). A wrong one leaves the hook untrusted, so it never runs.
    """
    handler = {"type": "command", "command": command, "timeout": timeout, "async": False}
    identity = {"event_name": "pre_tool_use", "hooks": [handler]}
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _toml(text: str) -> str:
    """A TOML basic string: JSON's escapes are TOML's."""
    return json.dumps(text, ensure_ascii=False)


def helpers() -> Path:
    """The folder of Nest's helper scripts, written again when something removed or changed
    one, as the system's cleaning of old temporary files can.
    """
    return helper_files(lambda folder: _scripts(folder, sys.executable), executable=True)


def helper_files(files: Callable[[Path], Mapping[str, str]], *, executable: bool = False) -> Path:
    """The helper folder with `files` (by name, made for the folder) written in it, again
    when one is missing or changed.
    """
    folder = _folder()
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files(folder).items():
        path = folder / name
        try:
            if path.read_text(encoding="utf-8") == text:
                continue
        except OSError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        written = path.with_suffix(".tmp")
        written.write_text(text, encoding="utf-8")
        written.chmod(0o755 if executable else 0o644)
        written.replace(path)
    return folder


@functools.cache
def _folder() -> Path:
    """One per daemon process, so a test's daemon never writes the live one's."""
    folder = Path(tempfile.mkdtemp(prefix="nest-push-block-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    return folder


def _scripts(folder: Path, python: str) -> dict[str, str]:
    check = f"{shlex.quote(python)} -I -m nestd.providers.push_check"
    return {
        GH: f"""#!/bin/sh
# Nest's gh for a run that may not push or write pull requests (push_block, D160).
{check} gh "$@" || exit 1
here={shlex.quote(str(folder))}
IFS=:
for dir in $PATH; do
\tif [ "$dir" != "$here" ] && [ -x "$dir/gh" ]; then
\t\texec "$dir/gh" "$@"
\tfi
done
echo "gh: command not found" >&2
exit 127
""",
        CODEX_HOOK: f"""#!/bin/sh
# Nest's PreToolUse hook for a Codex chat's subagents (push_block, B127): only their
# events name an agent_id, and only those need the check.
# If the check cannot run, the call is refused.
input=$(cat)
case $input in
*'"agent_id"'*)
\tprintf '%s' "$input" | {check} hook && exit 0
\tprintf '%s' {shlex.quote(json.dumps(DENY))}
\t;;
esac
""",
        GROK_HOOK: f"""#!/bin/sh
# Nest's command hook for a guarded Grok Build run's shell commands (B153), behind Nest's
# own answer to Grok's hook. Grok refuses the call when this fails.
exec {check} grok-hook
""",
    }
