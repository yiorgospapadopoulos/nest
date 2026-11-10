"""Whether a shell command line could push, or open or merge a pull request, or write to
GitHub through `gh` (D049, D160). Commits are allowed (pixies may commit, 2026-10-21);
`pushes=False` leaves all that out, `worktrees` flags removing a worktree too (Autopilot),
and with neither nothing is flagged.

A few lines are plainly harmless and pass first, on the raw text. All of the line must fit,
and anything else goes to the strict check below, which refuses when in doubt:
- one `grep`, `rg` or `echo` with no newline and none of `$`, a backtick, `;`, `&`, `|`,
  `<`, `>`, `(`, `)`, even in quotes. A plain `cd <dir> &&` may come first, and
  `2>/dev/null` and a pipe to `head`, `tail` or `wc -l` may come last;
- `docker push <one word>`, whose word may hold plain variables;
- `git commit -m "$(cat <<'EOF'` with a quoted delimiter, the message, the delimiter and
  `)"`, with nothing before or after. Codex's shell wrapper is seen through for the other
  two only, since a double-quoted wrapper would expand this one's `$(` first.

The strict check reads the line the way a shell reads it: `shlex` resolves quotes and
escapes, `;`, `&`, `|`, `(`, `)`, `<`, `>`, newlines and backticks separate commands, and
`#` starts nothing. Every word named `git` or `gh` (any path, any case, since the Mac's file
system ignores case) is checked from there, so prefixes and wrappers (`FOO=1`, `env`,
`command`, `xargs`, `timeout`, `sudo`, `{`, `then`) need no special case. For git, global
options are stepped over with their values (`-C "a dir"`, `-c k=v`, `--git-dir x`) and
`-c alias.x=...` aliases are expanded, as is what `git config alias.x ...` defines. A line
that runs git and sets git config through the environment (`GIT_CONFIG_COUNT`,
`GIT_CONFIG_KEY_<n>`, `GIT_CONFIG_VALUE_<n>`, `GIT_CONFIG_PARAMETERS`, as a prefix, through
`env` or `export`) is a write: it can define an alias or undo the push block's own settings,
which use the same variables. For gh, flags may stand before or after the group.

`gh api` passes only when it is clearly a read: no method but GET, and no field or input
without `-X GET`. `gh api graphql` with fields passes only with no `mutation`, no `@`, no
`--input` and nothing the shell expands. `gh repo sync` and `gh alias` writes are refused
too, and so is what hands out the token or a stored password: every `gh auth` action but
`status` without `-t` or `--show-token`, `git credential` and git's credential helpers.
Other gh writes, such as `gh release create`, are not looked at.

A word that holds a command line of its own (`sh -c "..."`, `eval "..."`,
`python -c "..."`, a heredoc) is checked too, and there a mere mention of git and a write
subcommand is enough. Denied when uncertain: a line that cannot be parsed (unbalanced
quotes), one that builds words at run time (`$`, backticks) and names a write subcommand,
or git with an unknown global option followed by a write subcommand.

Read-only commands that mention the words elsewhere (`git log --grep push`,
`git diff src/push.ts`, `git stash push`) are allowed. Accepted false refusals: a line that
only mentions a blocked command but is not one of the harmless ones (`cat <<E > n.md` with
`git push` inside, `echo "$X git push"`, `git commit -m "fix git push"`).

A script written first and run later is not seen here: a guarded run's own programs meet
its push block instead (`push_block`, D160).
"""

import re
import shlex
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from posixpath import basename

from nestd.providers.codex_items import shown_command

# Subcommands that send worktrees to a remote.
GIT_WRITES = frozenset({"push", "send-pack", "http-push"})
_DASHED_WRITES = frozenset(f"git-{name}" for name in GIT_WRITES)
# `git credential fill` and the helpers (`git credential-osxkeychain get`) print a stored
# password (B159 R03).
_CREDENTIAL = "credential"
# `gh pr new` is gh's own alias of `gh pr create`.
_GH_WRITES = {
    "pr": frozenset({"create", "merge", "new"}),
    "repo": frozenset({"sync"}),
    "alias": frozenset({"set", "import"}),
}
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
# git config set through the environment (B159 recheck 2 F).
_CONFIG_ENV = re.compile(r"GIT_CONFIG_(?:COUNT|PARAMETERS|KEY_\w*|VALUE_\w*)=")
_RUNS_GIT = re.compile(r"\bgit\b", re.IGNORECASE)

_SEPARATOR = re.compile(r"^[;&|()<>]+$")
# A word with any of these may hold a command line of its own.
_NESTED = re.compile(r"[\s;&|()<>`$]")
_DYNAMIC = re.compile(r"[$`]")
_WRITE_WORD = re.compile(r"\b(?:push|send-pack|http-push)\b", re.IGNORECASE)
_GIT_MENTION = re.compile(r"\bgit\b.*?\b(?:push|send-pack|http-push)\b", re.I | re.S)
_GH_MENTION = re.compile(r"\bgh\b.*?\bpr\b.*?\b(?:create|merge|new)\b", re.I | re.S)
# Both words, in any order: a variable can hold either.
_WORKTREE_REMOVE = re.compile(r"(?=.*\bworktree\b).*\bremove\b", re.I | re.S)
_GH_DYNAMIC = re.compile(r"\bpr\b.*?\b(?:create|merge|new)\b", re.I | re.S)

# `gh auth status -t` in any cluster of short flags.
_SHOW_TOKEN_SHORT = re.compile(r"-[a-zA-Z]*t[a-zA-Z]*")

_GH_API_METHODS = frozenset({"-X", "--method"})
_GH_API_SENDS = frozenset({"-f", "-F", "--field", "--raw-field", "--input"})
_GH_API_LONG_VALUES = frozenset(
    {
        *("--method", "--field", "--raw-field", "--input", "--header", "--jq"),
        *("--template", "--preview", "--cache", "--hostname"),
    }
)
# `-X` or a field in any cluster, or a long one; a built word can hide what comes after it.
_GH_API_SEND_FLAG = re.compile(r"\s(?:-[a-zA-Z]*[xXfF]|--(?:method|field|raw-field|input))")
_GRAPHQL_WRITE = re.compile(r"mutation|@", re.IGNORECASE)
_QUOTED = re.compile(r"""\\.|'[^']*'|"(?:\\.|[^"\\])*\"""", re.DOTALL)

_TEXT_LINE = re.compile(r"(?:grep|rg|echo)[ \t][^\n$`;&|<>()]*")
_CD_FIRST = re.compile(
    r"""\Acd[ \t]+(?:"[^"\n$`\\]*"|'[^'\n]*'|[^\s;&|<>()$`'"\\]+)[ \t]*&&[ \t]*"""
)
_SHORT_OUTPUT = re.compile(
    r"(?:[ \t]+2>/dev/null)?(?:[ \t]*\|[ \t]*(?:(?:head|tail)(?:[ \t]+-n?[ \t]*\d+)?|wc -l))?\Z"
)
_DOCKER_PUSH = re.compile(r'docker[ \t]+push[ \t]+("?)(?:[\w./:@-]|\$\w+|\$\{\w+\})+\1')
_COMMIT_FLAGS = r"(?:[ \t]+(?:-a|--all|--amend|--no-verify|-s|--signoff))*"
_COMMIT_HEREDOC = re.compile(rf"""git commit{_COMMIT_FLAGS}[ \t]+-a?m[ \t]+"\$\(cat <<'(\w+)'""")
# A `(...)` on one line, with no quote or escape that could hide only one of its ends.
_PLAIN_PARENS = re.compile(r"""(?<!\\)\([^()'"`\\\n]*\)""")


@dataclass(frozen=True)
class _Watch:
    """What counts as a write."""

    pushes: bool
    worktrees: bool


def is_git_write(command: str, *, pushes: bool = True, worktrees: bool = False) -> bool:
    if not (pushes or worktrees) or _plainly_harmless(command):
        return False
    return _writes(command, nested=False, watch=_Watch(pushes, worktrees))


def _plainly_harmless(command: str) -> bool:
    line = command.strip()
    inner = shown_command(line)
    return _only_text(inner) or bool(_DOCKER_PUSH.fullmatch(inner)) or _commit_from_heredoc(line)


def _only_text(line: str) -> bool:
    """`rg --pre` runs a program on each file."""
    line = _SHORT_OUTPUT.sub("", _CD_FIRST.sub("", line, count=1), count=1)
    if _TEXT_LINE.fullmatch(line) is None:
        return False
    return not (line.startswith("rg") and "--pre" in _unquoted(line))


def _commit_from_heredoc(line: str) -> bool:
    """The delimiter is quoted, so the shell expands nothing in the message. But bash 3.2,
    `/bin/bash` and `/bin/sh` on a Mac, ends the `$(` at the first unmatched `)` even inside
    a heredoc and runs what follows, so a `)` must pair up with a `(` beside it.
    """
    head, *rest = line.split("\n")
    found = _COMMIT_HEREDOC.fullmatch(head)
    if found is None or rest[-2:] != [found[1], ')"']:
        return False
    body = rest[:-2]
    return found[1] not in body and ")" not in _PLAIN_PARENS.sub("", "\n".join(body))


def _writes(text: str, *, nested: bool, watch: _Watch) -> bool:
    if nested and _mentions_write(text, watch):
        return True
    if _DYNAMIC.search(text) and (
        (watch.pushes and (_WRITE_WORD.search(text) or _GH_DYNAMIC.search(text)))
        or (watch.worktrees and _WORKTREE_REMOVE.search(text))
    ):
        return True
    try:
        words = _words(text)
    except ValueError:  # unbalanced quotes
        return _mentions_write(text, watch)
    return _words_write(words, text, watch)


def _mentions_write(text: str, watch: _Watch) -> bool:
    plain = _unquoted(text)
    if watch.worktrees and _WORKTREE_REMOVE.search(plain):
        return True
    return watch.pushes and bool(_GIT_MENTION.search(plain) or _GH_MENTION.search(plain))


def _unquoted(text: str) -> str:
    return re.sub(r"[\"'\\]", "", text)


def _words(text: str) -> list[str]:
    text = text.replace("\\\n", "").replace("\n", ";").replace("`", ";")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _words_write(words: Sequence[str], text: str, watch: _Watch) -> bool:
    """`text` is the line; only shorter words are read again, so reading ends."""
    if watch.pushes and any(_CONFIG_ENV.match(word) for word in words) and _RUNS_GIT.search(text):
        return True
    for index, word in enumerate(words):
        name = basename(word).lower()
        if watch.pushes and (name in _DASHED_WRITES or name.startswith(f"git-{_CREDENTIAL}")):
            return True
        if name == "git" and _git_writes(words[index + 1 :], {}, watch):
            return True
        if (
            watch.worktrees
            and name == "git-worktree"
            and _removes_worktree(_until_separator(words[index + 1 :]))
        ):
            return True
        if watch.pushes and name == "gh" and _gh_writes(words[index + 1 :], text):
            return True
        if (
            len(word) < len(text)
            and not _SEPARATOR.match(word)
            and _NESTED.search(word)
            and _writes(word, nested=True, watch=watch)
        ):
            return True
    return False


def _git_writes(args: Sequence[str], aliases: dict[str, str | None], watch: _Watch) -> bool:
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
    if _subcommand_writes(subcommand, tail, watch):
        return True
    if subcommand in aliases:
        return _alias_writes(aliases.pop(subcommand), tail, aliases, watch)
    return watch.pushes and uncertain and any(word.lower() in GIT_WRITES for word in rest)


def _subcommand_writes(subcommand: str, tail: Sequence[str], watch: _Watch) -> bool:
    lowered = [word.lower() for word in tail]
    if watch.pushes and (
        subcommand in GIT_WRITES
        or (subcommand == "subtree" and "push" in lowered)
        or subcommand.startswith(_CREDENTIAL)
    ):
        return True
    if watch.worktrees and subcommand == "worktree" and _removes_worktree(lowered):
        return True
    # Defining an alias that pushes, to run it later.
    if subcommand != "config":
        return False
    at = next((i for i, word in enumerate(lowered) if word.startswith(_ALIAS_PREFIX)), None)
    if at is None:
        return False
    definition = " ".join(tail)
    return bool(
        (watch.pushes and _WRITE_WORD.search(definition))
        or (watch.worktrees and _WORKTREE_REMOVE.search(definition))
        # Read as the alias would run, which also finds `credential` (B159 recheck 1).
        or _alias_writes(" ".join(tail[at + 1 :]), [], {}, watch)
    )


def _removes_worktree(tail: Sequence[str]) -> bool:
    """A worktree action held in a variable could be `remove`."""
    return "remove" in tail or (len(tail) > 0 and bool(_DYNAMIC.search(tail[0])))


def _alias_writes(
    expansion: str | None, tail: Sequence[str], aliases: dict[str, str | None], watch: _Watch
) -> bool:
    if expansion is None:  # set from an environment variable, so unknown here
        return True
    if expansion.startswith("!"):
        return _writes(expansion[1:], nested=True, watch=watch)
    try:
        expanded = shlex.split(expansion)
    except ValueError:
        return True
    return _git_writes([*expanded, *tail], aliases, watch)


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


def _gh_writes(args: Sequence[str], text: str) -> bool:
    """`gh pr create|new|merge` and the like, with flags and their values anywhere before
    the action, and `gh api`. A group or action built at run time could be any of them.
    """
    group = ""
    previous = ""
    for index, arg in enumerate(args):
        word = arg.lower()
        if group and word in _GH_WRITES[group]:
            return True
        if word.startswith("-") or (previous.startswith("-") and "=" not in previous):
            previous = word
            continue
        if _DYNAMIC.search(word):
            return True
        if not group and word == "api":
            return _gh_api_writes(args[index + 1 :], text)
        if not group and word == "auth":
            return _gh_auth_reveals(args[index + 1 :])
        if group or word not in _GH_WRITES:
            return False
        group = word
        previous = word
    return False


def _gh_api_writes(args: Sequence[str], text: str) -> bool:
    """Everything but a clear read. A `$(...)` splits the words, so what follows it is only
    in `text`, and a word that is all variable can hold flags.
    """
    if ("$(" in text or "`" in text) and _GH_API_SEND_FLAG.search(text):
        return True
    call = _until_separator(args)
    if any(word.startswith("$") for word in call):
        return True
    flags, others = _gh_api_flags(call)
    names = {name for name, _ in flags}
    if others[:1] == ["graphql"]:
        return (
            "--input" in names
            or bool(_GRAPHQL_WRITE.search(" ".join(args)))
            or _shell_expands(text)
        )
    methods = {value.upper() for name, value in flags if name in _GH_API_METHODS}
    return methods != {"GET"} if methods else bool(names & _GH_API_SENDS)


def _gh_auth_reveals(args: Sequence[str]) -> bool:
    """Every action but `status` could hand out the token (`token`, `git-credential get`,
    a login), and so does `status -t`; `gh auth` alone shows help."""
    call = _until_separator(args)
    action = next((word.lower() for word in call if not word.startswith("-")), None)
    if action != "status":
        return action is not None
    return any(
        _DYNAMIC.search(word)
        or word.partition("=")[0] == "--show-token"
        or _SHOW_TOKEN_SHORT.fullmatch(word)
        for word in call
    )


def _gh_api_flags(call: Sequence[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """The call's flags as name and value, and its other words. Short flags may be joined
    (`-XPUT`, `-iX PUT`): `-i` is the only one with no value.
    """
    flags: list[tuple[str, str]] = []
    others: list[str] = []
    words: Iterator[str] = iter(call)
    for word in words:
        if word.startswith("--"):
            name, given, value = word.partition("=")
            flags.append(
                (name, next(words, "") if name in _GH_API_LONG_VALUES and not given else value)
            )
        elif word.startswith("-") and word != "-":
            short = word[1:].lstrip("i")
            if short:
                flags.append((f"-{short[0]}", short[1:].removeprefix("=") or next(words, "")))
        else:
            others.append(word)
    return flags, others


def _shell_expands(text: str) -> bool:
    """A `$` in single quotes is a GraphQL variable, which is fine."""
    outside = _QUOTED.sub(lambda quoted: "" if quoted[0][0] == "'" else quoted[0], text)
    return bool(_DYNAMIC.search(outside))


def _until_separator(words: Sequence[str]) -> list[str]:
    kept: list[str] = []
    for word in words:
        if _SEPARATOR.match(word):
            break
        kept.append(word)
    return kept
