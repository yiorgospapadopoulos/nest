from pathlib import Path

import pytest

from nestd.config.models import PermissionMode
from nestd.providers.codex_modes import (
    CodexPermissions,
    codex_permissions,
    command_decision,
    file_change_decision,
)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (None, ("untrusted", "workspace-write", "user")),
        ("default", ("untrusted", "workspace-write", "user")),
        ("acceptEdits", ("untrusted", "workspace-write", "user")),
        ("plan", ("never", "read-only", "user")),
        ("auto", ("on-request", "workspace-write", "auto_review")),
        ("bypassPermissions", ("never", "danger-full-access", "user")),
    ],
)
def test_each_mode_maps_to_an_approval_policy_sandbox_and_reviewer(
    mode: PermissionMode | None, expected: tuple[str, str, str]
) -> None:
    permissions = codex_permissions(mode, guarded=False)

    assert (permissions.approval_policy, permissions.sandbox, permissions.reviewer) == expected
    assert permissions.network


@pytest.mark.parametrize("mode", ["default", "acceptEdits", "auto", "bypassPermissions"])
def test_a_guarded_run_asks_nest_for_every_command_with_no_extra_sandbox(
    tmp_path: Path, mode: PermissionMode
) -> None:
    """As Claude's guarded runs: full access and network; Nest sees every command and edit
    Codex does not know to be read-only (B112).
    """
    permissions = codex_permissions(mode, guarded=True, write_root=tmp_path)

    assert permissions == CodexPermissions("untrusted", "danger-full-access", "user", network=True)


def test_a_guarded_run_in_plan_mode_stays_read_only_and_still_asks() -> None:
    assert codex_permissions("plan", guarded=True) == CodexPermissions(
        "untrusted", "read-only", "user", network=True
    )


def test_a_write_root_makes_every_file_change_come_to_nest(tmp_path: Path) -> None:
    permissions = codex_permissions("bypassPermissions", guarded=False, write_root=tmp_path)

    assert (permissions.approval_policy, permissions.reviewer) == ("untrusted", "user")


def test_sandbox_policies_follow_the_sandbox(tmp_path: Path) -> None:
    write = codex_permissions("default", guarded=False).sandbox_policy([tmp_path])

    assert write == {
        "type": "workspaceWrite",
        "writableRoots": [str(tmp_path)],
        "networkAccess": True,
        "excludeTmpdirEnvVar": False,
        "excludeSlashTmp": False,
    }
    assert codex_permissions("plan", guarded=False).sandbox_policy([]) == {
        "type": "readOnly",
        "networkAccess": True,
    }
    assert codex_permissions("default", guarded=True).sandbox_policy([]) == {
        "type": "dangerFullAccess"
    }


@pytest.mark.parametrize(
    "command",
    ["git push origin wip", "git -C repo push", "gh pr create --fill", "sh -c 'git push'"],
)
def test_a_guarded_run_declines_git_writes_in_every_mode(command: str) -> None:
    for mode in ("default", "bypassPermissions", None):
        assert command_decision(command, mode, guarded=True) == "decline"


def test_a_guarded_run_may_commit() -> None:
    assert command_decision("git commit -m wip", "bypassPermissions", guarded=True) == "accept"
    assert command_decision("git commit -m wip", "default", guarded=True) is None


def test_git_writes_go_to_the_user_in_a_normal_chat() -> None:
    assert command_decision("git push", "default", guarded=False) is None


def test_other_commands_are_accepted_in_bypass_and_asked_otherwise() -> None:
    assert command_decision("npm test", "bypassPermissions", guarded=True) == "accept"
    assert command_decision("git status", "default", guarded=True) is None
    assert command_decision("npm test", "acceptEdits", guarded=False) is None


def test_file_changes_are_accepted_when_edits_are_and_never_in_plan_mode() -> None:
    assert file_change_decision("acceptEdits") == "accept"
    assert file_change_decision("bypassPermissions") == "accept"
    assert file_change_decision("default") is None
    assert file_change_decision(None) is None
    assert file_change_decision("plan") == "decline"


def test_autopilot_declines_commits_a_pixie_may_make() -> None:
    assert command_decision("git commit -m x", "bypassPermissions", True, True) == "decline"
    assert command_decision("git commit -m x", "bypassPermissions", True) == "accept"
