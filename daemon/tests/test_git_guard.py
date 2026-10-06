import pytest
from claude_agent_sdk.types import HookContext, PreToolUseHookInput, UserPromptSubmitHookInput

from harness.providers.git_guard import DENY_REASON, GIT_WRITE_RULES, block_git_writes, is_git_write

BLOCKED = [
    "git commit -m 'x'",
    "git push",
    "git push origin main --force",
    "cd sub && git commit --allow-empty -m b",
    "true; git push",
    "ls | xargs git commit -m x",
    "sh -c 'git commit --allow-empty -m c'",
    'bash -lc "git push origin HEAD"',
    "git -c user.name=x commit --allow-empty -m d",
    "git -C /tmp/repo push",
    "git --no-pager -c a=b -C dir commit",
    "git --git-dir /x/.git --work-tree /x commit -am y",
    "git --git-dir=/x/.git push",
    "/usr/bin/git commit -m x",
    "env GIT_AUTHOR_NAME=x git commit",
    "sudo git push",
    "git 'commit' -m quoted",
    "echo $(git commit -m inline)",
    "git\tcommit",
    "git commit-tree HEAD^{tree}",
    "gh pr create --fill",
    "gh  pr   merge 12 --squash",
    "cd x && gh pr create",
    # Accepted false positives: the command only mentions a blocked command.
    "echo 'git commit'",
    'grep -r "git push" docs',
]

ALLOWED = [
    "git status",
    "git diff",
    "git log --grep commit",
    "git log --oneline -- push.py",
    "git diff src/commit.ts",
    "git show HEAD:commit/handler.py",
    "git stash push -m wip",
    "git lfs push origin",
    "git-commit-helper",
    "legit commit",
    "gh pr view 3",
    "gh pr list",
    "gh issue create",
    "npm run commit-lint",
    "",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks_commits_pushes_and_pull_request_writes(command: str) -> None:
    assert is_git_write(command) is True


@pytest.mark.parametrize("command", ALLOWED)
def test_allows_read_only_and_unrelated_commands(command: str) -> None:
    assert is_git_write(command) is False


def test_permission_rules_cover_the_same_commands() -> None:
    assert GIT_WRITE_RULES == (
        "Bash(git commit:*)",
        "Bash(git push:*)",
        "Bash(gh pr create:*)",
        "Bash(gh pr merge:*)",
    )


def pre_tool_use(tool_input: dict[str, object]) -> PreToolUseHookInput:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "transcript_path": "/t",
        "cwd": "/c",
        "tool_name": "Bash",
        "tool_input": tool_input,
        "tool_use_id": "tu1",
        "agent_id": "a",
        "agent_type": "main",
    }


CONTEXT: HookContext = {"signal": None}


async def test_hook_denies_blocked_bash_commands_with_a_reason() -> None:
    output = await block_git_writes(pre_tool_use({"command": "git push"}), "tu1", CONTEXT)

    assert output == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_REASON,
        }
    }
    assert DENY_REASON == (
        "harness: commits, pushes and pull requests are made by harness after you approve them"
    )


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
