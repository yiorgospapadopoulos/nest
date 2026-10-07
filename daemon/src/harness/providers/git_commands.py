"""Whether a shell command line could commit, push, or open or merge a pull request (D049).

The line is read the way a shell reads it: `shlex` resolves quotes and escapes, `;`, `&`,
`|`, `(`, `)`, `<`, `>`, newlines and backticks separate commands, and `#` starts nothing.
Every word named `git` or `gh` (any path, any case, since the Mac's file system ignores
case) is checked from there, so prefixes and wrappers (`FOO=1`, `env`, `command`, `xargs`,
`timeout`, `sudo`, `{`, `then`) need no special case. For git, global options are stepped
over with their values (`-C "a dir"`, `-c k=v`, `--git-dir x`) and `-c alias.x=...`
aliases are expanded. For gh, flags may stand before or after `pr`.

A word that holds a command line of its own (`sh -c "..."`, `eval "..."`,
`python -c "..."`, a heredoc) is checked too, and there a mere mention of git and a write
subcommand is enough. Denied when uncertain: a line that cannot be parsed (unbalanced
quotes), one that builds words at run time (`$`, backticks) and names a write subcommand,
or git with an unknown global option followed by a write subcommand.

Read-only commands that mention the words elsewhere (`git log --grep commit`,
`git diff src/commit.ts`, `git stash push`) are allowed. Accepted false positives: text that
merely mentions a blocked command (`echo "git push"`), and `$` lines that name commit or
push for something else (`docker push $IMAGE`).
"""

import re
import shlex
from collections.abc import Sequence
from posixpath import basename

# Subcommands that create commits or send them to a remote.
GIT_WRITES = frozenset({"commit", "commit-tree", "push", "send-pack", "http-push"})
_DASHED_WRITES = frozenset(f"git-{name}" for name in GIT_WRITES)
# `gh pr new` is gh's own alias of `gh pr create`.
_GH_PR_WRITES = frozenset({"create", "merge", "new"})
# git's global options that take the next word as their value.
_GIT_VALUE_OPTIONS = frozenset(
    {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix"}
)
_GIT_FLAGS = frozenset(
    {
        *("-p", "--paginate", "-P", "--no-pager", "--bare", "--no-replace-objects"),
        *("--no-lazy-fetch", "--no-optional-locks", "--no-advice", "--literal-pathspecs"),
        *("--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs", "--exec-path"),
        *("--html-path", "--man-path", "--info-path", "-v", "--version", "-h", "--help"),
    }
)
_ALIAS_PREFIX = "alias."

_SEPARATOR = re.compile(r"^[;&|()<>]+$")
# A word with any of these may hold a command line of its own.
_NESTED = re.compile(r"[\s;&|()<>`$]")
_DYNAMIC = re.compile(r"[$`]")
_WRITE_WORD = re.compile(r"\b(?:commit|push|send-pack|http-push)\b", re.IGNORECASE)
_GIT_MENTION = re.compile(r"\bgit\b.*?\b(?:commit|push|send-pack|http-push)\b", re.I | re.S)
_GH_MENTION = re.compile(r"\bgh\b.*?\bpr\b.*?\b(?:create|merge|new)\b", re.I | re.S)
_GH_DYNAMIC = re.compile(r"\bpr\b.*?\b(?:create|merge|new)\b", re.I | re.S)


def is_git_write(command: str) -> bool:
    return _writes(command, nested=False)


def _writes(text: str, *, nested: bool) -> bool:
    if nested and _mentions_write(text):
        return True
    if _DYNAMIC.search(text) and (_WRITE_WORD.search(text) or _GH_DYNAMIC.search(text)):
        return True
    try:
        words = _words(text)
    except ValueError:  # unbalanced quotes
        return _mentions_write(text)
    return _words_write(words, len(text))


def _mentions_write(text: str) -> bool:
    plain = re.sub(r"[\"'\\]", "", text)
    return bool(_GIT_MENTION.search(plain) or _GH_MENTION.search(plain))


def _words(text: str) -> list[str]:
    text = text.replace("\\\n", "").replace("\n", ";").replace("`", ";")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _words_write(words: Sequence[str], length: int) -> bool:
    """`length` is the line's; only shorter words are read again, so reading ends."""
    for index, word in enumerate(words):
        name = basename(word).lower()
        if name in _DASHED_WRITES:
            return True
        if name == "git" and _git_writes(words[index + 1 :], {}):
            return True
        if name == "gh" and _gh_writes(words[index + 1 :]):
            return True
        if (
            len(word) < length
            and not _SEPARATOR.match(word)
            and _NESTED.search(word)
            and _writes(word, nested=True)
        ):
            return True
    return False


def _git_writes(args: Sequence[str], aliases: dict[str, str | None]) -> bool:
    aliases = dict(aliases)
    uncertain = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in _GIT_VALUE_OPTIONS:
            _note_alias(arg, args[index + 1] if index + 1 < len(args) else "", aliases)
            index += 2
        elif arg.startswith("--") and "=" in arg:
            option, value = arg.split("=", 1)
            _note_alias(option, value, aliases)
            index += 1
        elif arg.startswith("-"):
            uncertain = uncertain or arg not in _GIT_FLAGS
            index += 1
        else:
            break
    rest = _until_separator(args[index:])
    if not rest:
        return False
    subcommand, tail = rest[0].lower(), rest[1:]
    if _subcommand_writes(subcommand, tail):
        return True
    if subcommand in aliases:
        return _alias_writes(aliases.pop(subcommand), tail, aliases)
    return uncertain and any(word.lower() in GIT_WRITES for word in rest)


def _subcommand_writes(subcommand: str, tail: Sequence[str]) -> bool:
    if subcommand in GIT_WRITES:
        return True
    lowered = [word.lower() for word in tail]
    if subcommand == "subtree":
        return "push" in lowered
    # Defining an alias that commits or pushes, to run it later.
    return (
        subcommand == "config"
        and any(word.startswith(_ALIAS_PREFIX) for word in lowered)
        and bool(_WRITE_WORD.search(" ".join(tail)))
    )


def _alias_writes(
    expansion: str | None, tail: Sequence[str], aliases: dict[str, str | None]
) -> bool:
    if expansion is None:  # set from an environment variable, so unknown here
        return True
    if expansion.startswith("!"):
        return _writes(expansion[1:], nested=True)
    try:
        expanded = shlex.split(expansion)
    except ValueError:
        return True
    return _git_writes([*expanded, *tail], aliases)


def _note_alias(option: str, value: str, aliases: dict[str, str | None]) -> None:
    key, has_value, expansion = value.partition("=")
    key = key.lower()
    if not key.startswith(_ALIAS_PREFIX):
        return
    name = key.removeprefix(_ALIAS_PREFIX)
    if option == "-c":
        aliases[name] = expansion if has_value else ""
    elif option == "--config-env":
        aliases[name] = None


def _gh_writes(args: Sequence[str]) -> bool:
    """`gh pr create|new|merge`, with flags and their values anywhere before the action."""
    in_pr = False
    previous = ""
    for word in (arg.lower() for arg in args):
        if in_pr and word in _GH_PR_WRITES:
            return True
        if word.startswith("-") or (previous.startswith("-") and "=" not in previous):
            previous = word
            continue
        if in_pr or word != "pr":
            return False
        in_pr = True
        previous = word
    return False


def _until_separator(words: Sequence[str]) -> list[str]:
    kept: list[str] = []
    for word in words:
        if _SEPARATOR.match(word):
            break
        kept.append(word)
    return kept
