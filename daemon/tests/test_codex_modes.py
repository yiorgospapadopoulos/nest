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
def test_a_guarded_run_asks_for_every_command_without_network(mode: PermissionMode) -> None:
    permissions = codex_permissions(mode, guarded=True)

    assert permissions == CodexPermissions("untrusted", "workspace-write", "user", network=False)


def test_a_guarded_run_in_plan_mode_stays_read_only() -> None:
    assert codex_permissions("plan", guarded=True).sandbox == "read-only"


def test_sandbox_policies_follow_the_sandbox(tmp_path: Path) -> None:
    write = codex_permissions("default", guarded=True).sandbox_policy([tmp_path])

    assert write == {
        "type": "workspaceWrite",
        "writableRoots": [str(tmp_path)],
        "networkAccess": False,
        "excludeTmpdirEnvVar": False,
        "excludeSlashTmp": False,
    }
    assert codex_permissions("plan", guarded=False).sandbox_policy([]) == {
        "type": "readOnly",
        "networkAccess": True,
    }
    assert codex_permissions("bypassPermissions", guarded=False).sandbox_policy([]) == {
        "type": "dangerFullAccess"
    }


@pytest.mark.parametrize(
    "command",
    ["git commit -m wip", "git -C repo push", "gh pr create --fill", "sh -c 'git push'"],
)
def test_a_guarded_run_declines_git_writes_in_every_mode(command: str) -> None:
    for mode in ("default", "bypassPermissions", None):
        assert command_decision(command, mode, guarded=True) == "decline"


def test_git_writes_go_to_the_user_in_a_normal_chat() -> None:
    assert command_decision("git commit -m wip", "default", guarded=False) is None


def test_other_commands_are_accepted_in_bypass_and_asked_otherwise() -> None:
    assert command_decision("npm test", "bypassPermissions", guarded=True) == "accept"
    assert command_decision("git status", "default", guarded=True) is None
    assert command_decision("npm test", "acceptEdits", guarded=False) is None


def test_file_changes_are_accepted_when_edits_are() -> None:
    assert file_change_decision("acceptEdits") == "accept"
    assert file_change_decision("bypassPermissions") == "accept"
    assert file_change_decision("default") is None
    assert file_change_decision(None) is None


@pytest.mark.parametrize(
    ("mode", "guarded", "expected"),
    [
        ("default", True, ("untrusted", "workspace-write")),
        ("bypassPermissions", True, ("untrusted", "workspace-write")),
        ("bypassPermissions", False, ("never", "workspace-write")),
        ("plan", False, ("never", "read-only")),
    ],
)
def test_a_run_with_a_write_root_never_gets_full_access(
    tmp_path: Path, mode: PermissionMode, guarded: bool, expected: tuple[str, str]
) -> None:
    permissions = codex_permissions(mode, guarded, write_root=tmp_path, cwd=tmp_path / "sub")

    assert (permissions.approval_policy, permissions.sandbox) == expected


def test_a_run_working_outside_its_write_root_is_read_only(tmp_path: Path) -> None:
    root = tmp_path / "workdir"

    permissions = codex_permissions("default", True, write_root=root, cwd=tmp_path / "repo")

    assert permissions.sandbox == "read-only"
