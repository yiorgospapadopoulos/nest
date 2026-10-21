import pytest
from claude_agent_sdk.types import HookContext, PreToolUseHookInput, UserPromptSubmitHookInput

from nestd.providers.git_guard import (
    DENY_REASON,
    GIT_WRITE_RULES,
    block_git_writes,
    is_git_write,
    tool_writes,
)

BLOCKED = [
    "git push -m 'x'",
    "git push",
    "git push origin main --force",
    "cd sub && git push --allow-empty -m b",
    "true; git push",
    "ls | xargs git push -m x",
    "sh -c 'git push --allow-empty -m c'",
    'bash -lc "git push origin HEAD"',
    "git -c user.name=x push --allow-empty -m d",
    "git -C /tmp/repo push",
    "git --no-pager -c a=b -C dir push",
    "git --git-dir /x/.git --work-tree /x push -am y",
    "git --git-dir=/x/.git push",
    "/usr/bin/git push -m x",
    "env GIT_AUTHOR_NAME=x git push",
    "sudo git push",
    "git 'push' -m quoted",
    "echo $(git push -m inline)",
    "git\tpush",
    "git send-pack origin HEAD",
    "gh pr create --fill",
    "gh  pr   merge 12 --squash",
    "cd x && gh pr create",
    # Quoted and escaped arguments.
    'git -C "my dir" push -m x',
    'git -c user.name="A B" push -m x',
    '"git" push -m x',
    "git -C 'dir with space' --no-pager push",
    'git --git-dir "/a b/.git" --work-tree "/a b" push',
    "g\\it push",
    "g\"i\"t pu'sh'",
    "git pu\\sh -m x",
    "git \\\n  push",
    'git push -m "unbalanced',
    # Environment prefixes and wrappers.
    "GIT_DIR=x git push",
    'FOO="a b" git push -m x',
    "command git push",
    "env -i PATH=/usr/bin git push",
    "exec git push",
    "timeout 60 git push",
    "nohup git push &",
    "nice -n 5 git push -m x",
    "xargs -I{} git -C {} push",
    "find . -name .git -execdir git push \\;",
    # Paths to git, and case on a case-insensitive file system.
    "'/usr/bin/git' push",
    "/opt/homebrew/bin/GIT push",
    "git PUSH -m x",
    "git Push",
    "/usr/libexec/git-core/git-push -m x",
    "git-push origin main",
    # Separators, subshells and groups.
    "(git push)",
    "{ git push; }",
    "git status;git push",
    "git status&&git push",
    "git status||git push",
    "git status|git push",
    "git status & git push",
    "git status\ngit push",
    "git log x#; git push",
    "f() { git push -m x; }; f",
    "if true; then git push; fi",
    "for r in a b; do git -C $r push; done",
    "git -C ';' push",
    # Shells and strings run as commands.
    "sh -c \"git -C 'a b' push\"",
    "bash -c 'cd \"a b\" && git push -m x'",
    "zsh -c \"eval 'git push'\"",
    'eval "git push"',
    "env -S 'git push'",
    "python3 -c \"import subprocess; subprocess.run(['git', 'push'])\"",
    "printf 'git push' | sh",
    "cat > ship.sh <<'EOF'\ngit push\nEOF",
    # Words built at run time.
    "$(echo git) push",
    "G=git; $G push",
    "`echo git` push",
    "x=`git push`",
    "cmd=push; git $cmd",
    "git $(echo push) -m x",
    # Aliases.
    "git -c alias.ship=push ship",
    "git -c alias.ci=push ci -m x",
    "git -c alias.CI=push ci -m x",
    "git -c 'alias.x=!git push' x",
    "git -c alias.x='!sh -c \"git push\"' x",
    "git -c alias.a=b -c alias.b=push a",
    "git --config-env=alias.x=VAR x",
    "git --config-env alias.x=VAR x",
    "git -c 'alias.x=log \"a' x",
    "git config alias.ci push",
    'git config --global alias.p "push --force"',
    # Other ways to send commits.
    "git subtree push --prefix=x origin main",
    "git send-pack origin main",
    "git http-push https://example.com/r.git main",
    # Unknown global options make the subcommand uncertain.
    "git --unknown-option x push",
    "git -P push",
    "git --no-pager --bare -p push",
    # gh with flags before or after pr.
    "gh -R o/r pr create",
    "gh --repo o/r pr merge 1",
    "gh pr --repo o/r create --fill",
    "gh pr -R o/r merge 3",
    "gh pr --repo=o/r merge 3",
    "gh pr new",
    '"gh" pr create',
    "GH_REPO=o/r gh pr create",
    "gh pr -R ';' create",
    # Accepted false positives: the command only mentions a blocked command.
    "echo 'git push'",
    'grep -r "git push" docs',
    "echo git push",
    "docker push $IMAGE",
]

ALLOWED = [
    "git status",
    "git diff",
    "git log --grep commit",
    "git log --oneline -- push.py",
    "git diff src/commit.ts",
    "git show HEAD:commit/handler.py",
    "git stash push -m wip",
    'git stash push -m "wip push"',
    "git lfs push origin",
    "git-commit-helper",
    "legit commit",
    "gh pr view 3",
    "gh pr list",
    "gh pr list --state open",
    "gh pr view 3 --json title",
    "gh pr checks 12",
    "gh issue create",
    "npm run commit-lint",
    # Claude initializes a plain folder project (D041).
    "git init",
    "git init -b main",
    "cd notes && git init && git add -A",
    "",
    # Normal reads with quoted arguments and options.
    'git -C "my dir" status',
    "git -C 'dir with space' diff --stat",
    'git log --format="%h %s" -5',
    "git add -A && git status",
    "git -c core.pager=cat log --oneline",
    "git -c alias.st=status st",
    "git -c alias.x=x x",
    "git -c alias.x x status",
    "git --namespace=alias.x=commit x",
    "git config user.name",
    "git config --get remote.origin.url",
    "git config alias.lg 'log --oneline'",
    "git remote -v",
    "git fetch origin",
    "git branch -a",
    "git rev-parse HEAD",
    "git show --stat HEAD",
    "git blame -L 1,5 README.md",
    "git worktree list",
    "git subtree split --prefix=x",
    'git diff HEAD~1 -- "src/push helper.ts"',
    "git diff $(git merge-base HEAD main)",
    'for f in *.py; do git diff "$f"; done',
    "cd ~/git && git status",
    "git -C x",
    "git --version",
    "gh",
    "gh pr",
    "gh pr view 3; echo create",
    "npm test && git status",
    'ls "my dir"',
    "cat <<EOF\nhello\nEOF",
    "echo committed",
    # Commits are allowed for pixies too (D123).
    "git co\\mmit -m x",
    "git commit -m 'x'",
    "cd sub && git commit --allow-empty -m b",
    "ls | xargs git commit -m x",
    "sh -c 'git commit --allow-empty -m c'",
    "git -c user.name=x commit --allow-empty -m d",
    "git --no-pager -c a=b -C dir commit",
    "git --git-dir /x/.git --work-tree /x commit -am y",
    "/usr/bin/git commit -m x",
    "env GIT_AUTHOR_NAME=x git commit",
    "git 'commit' -m quoted",
    "echo $(git commit -m inline)",
    "git\tcommit",
    "git commit-tree HEAD^{tree}",
    'git -C "my dir" commit -m x',
    'git -c user.name="A B" commit -m x',
    '"git" commit -m x',
    'git commit -m "unbalanced',
    'FOO="a b" git commit -m x',
    "nice -n 5 git commit -m x",
    "git COMMIT -m x",
    "/usr/libexec/git-core/git-commit -m x",
    "f() { git commit -m x; }; f",
    "bash -c 'cd \"a b\" && git commit -m x'",
    "git $(echo commit) -m x",
    "git -c alias.ci=commit ci -m x",
    "git -c alias.CI=commit ci -m x",
    "git -c alias.x='!sh -c \"git commit\"' x",
    "git -c alias.a=b -c alias.b=commit a",
    "git config alias.ci commit",
    "echo 'git commit'",
    "echo git commit",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks_pushes_and_pull_request_writes(command: str) -> None:
    assert is_git_write(command) is True


@pytest.mark.parametrize("command", ALLOWED)
def test_allows_read_only_and_unrelated_commands(command: str) -> None:
    assert is_git_write(command) is False


def test_permission_rules_cover_the_same_commands() -> None:
    assert GIT_WRITE_RULES == (
        "Bash(git push:*)",
        "Bash(gh pr create:*)",
        "Bash(gh pr merge:*)",
    )


TOOL_WRITES: list[tuple[str, dict[str, object]]] = [
    # Any tool whose input carries a command line or argv.
    ("mcp__plugin_serena_serena__execute_shell_command", {"command": "git push"}),
    ("Monitor", {"command": "git -C 'a b' push", "description": "watch"}),
    ("mcp__shell__run", {"cmd": "git push origin x"}),
    ("mcp__shell__run", {"script": "cd x\ngit push"}),
    ("mcp__shell__run", {"shellCommand": "gh pr create"}),
    ("mcp__shell__run", {"command_line": "git push"}),
    ("mcp__proc__spawn", {"args": ["git", "push"]}),
    ("mcp__proc__spawn", {"argv": ["sh", "-c", "git push origin x"]}),
    ("mcp__proc__spawn", {"command": ["git", "push", 3]}),
    # MCP tools that open or merge pull requests or write to a remote by themselves.
    ("mcp__github__create_pull_request", {"title": "x"}),
    ("mcp__github__merge_pull_request", {"pull_number": 1}),
    ("mcp__github__push_files", {"files": []}),
    ("mcp__github__create_or_update_file", {"path": "a"}),
    ("mcp__github__create_commit", {"message": "x"}),
    ("mcp__git__git_push", {}),
    ("mcp__plugin_engineering_github__createPullRequest", {}),
]

TOOL_PASSES: list[tuple[str, dict[str, object]]] = [
    ("Bash", {"command": "git status"}),
    ("Bash", {"command": 3}),
    ("Bash", {}),
    ("Edit", {"file_path": "a.sh", "old_string": "x", "new_string": "git push"}),
    ("Write", {"file_path": "ship.sh", "content": "git push\n"}),
    ("Skill", {"skill": "x", "args": "git push"}),
    ("mcp__plugin_serena_serena__execute_shell_command", {"command": "git status"}),
    ("mcp__github__get_pull_request", {"pull_number": 1}),
    ("mcp__github__list_commits", {}),
    ("mcp__github__create_issue", {"title": "push the release"}),
    ("mcp__git__git_status", {}),
    ("mcp__git__git_commit", {"message": "x"}),
    ("Bash", {"command": "git commit -m x"}),
    ("git_push_helper", {}),
]


@pytest.mark.parametrize(("tool_name", "tool_input"), TOOL_WRITES)
def test_tools_that_run_or_are_git_writes_are_caught(
    tool_name: str, tool_input: dict[str, object]
) -> None:
    assert tool_writes(tool_name, tool_input) is True


@pytest.mark.parametrize(("tool_name", "tool_input"), TOOL_PASSES)
def test_other_tools_and_inputs_pass(tool_name: str, tool_input: dict[str, object]) -> None:
    assert tool_writes(tool_name, tool_input) is False


def pre_tool_use(tool_input: dict[str, object], tool_name: str = "Bash") -> PreToolUseHookInput:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "transcript_path": "/t",
        "cwd": "/c",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": "tu1",
        "agent_id": "a",
        "agent_type": "main",
    }


CONTEXT: HookContext = {"signal": None}
DENIED = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": DENY_REASON,
    }
}


async def test_hook_denies_blocked_bash_commands_with_a_reason() -> None:
    output = await block_git_writes(pre_tool_use({"command": "git push"}), "tu1", CONTEXT)

    assert output == DENIED
    assert DENY_REASON == (
        "Nest: pixies may commit, but pushing and opening or merging pull requests is left to you"
    )


async def test_hook_denies_other_tools_that_would_write() -> None:
    serena = pre_tool_use(
        {"command": 'git -C "a b" push'}, "mcp__plugin_serena_serena__execute_shell_command"
    )
    github = pre_tool_use({"title": "x"}, "mcp__github__create_pull_request")

    assert await block_git_writes(serena, "tu1", CONTEXT) == DENIED
    assert await block_git_writes(github, "tu1", CONTEXT) == DENIED


@pytest.mark.parametrize("tool_input", [{"command": "git status"}, {"command": 3}, {}])
async def test_hook_passes_other_commands_through(tool_input: dict[str, object]) -> None:
    assert await block_git_writes(pre_tool_use(tool_input), "tu1", CONTEXT) == {}


async def test_hook_ignores_other_hook_events() -> None:
    prompt: UserPromptSubmitHookInput = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s",
        "transcript_path": "/t",
        "cwd": "/c",
        "prompt": "git push",
    }

    assert await block_git_writes(prompt, None, CONTEXT) == {}
