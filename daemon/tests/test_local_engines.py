"""Claude Code and Codex pointed at a local model for one run (B106)."""

import json
from pathlib import Path

from nestd.local.run import LocalRun, claude_env, codex_config
from nestd.providers.base import PermissionDecision, SessionSpec, UserInput
from nestd.providers.claude import build_options
from nestd.providers.git_guard import GIT_WRITE_RULES
from tests.codex_support import SIGNED_OUT, FakeAppServer
from tests.recording_sink import RecordingSink
from tests.test_claude_provider import ScriptedHandler
from tests.test_codex_provider import Handler, provider


def local(*, context: int | None = 65536) -> LocalRun:
    return LocalRun(
        model_id="lm_1",
        model="qwen/qwen3-coder-30b",
        context=context,
        vision=False,
        thinking=True,
        base_url_for_claude="http://127.0.0.1:1234",
        key_for_claude="nest-local",
        base_url_for_codex="http://127.0.0.1:8765/local/ls_1/v1",
        key_for_codex="tk",
    )


def test_a_local_claude_run_goes_to_the_server_whatever_the_user_set(tmp_path: Path) -> None:
    run = local()
    options = build_options(
        SessionSpec(
            cwd=tmp_path,
            permission_mode="default",
            model="local:lm_1",
            effort="high",
            local=run,
            guard_git=False,
        ),
        ScriptedHandler(PermissionDecision("allow")),
        tmp_path / "gh",
        shell_env={"ANTHROPIC_BASE_URL": "https://elsewhere", "HOME": "/Users/me"},
    )

    assert options.model == "qwen/qwen3-coder-30b"
    assert options.effort == "high"
    assert options.env is not None
    assert {name: options.env[name] for name in claude_env(run)} == claude_env(run)
    assert options.env["HOME"] == "/Users/me"
    assert options.settings is not None
    assert json.loads(options.settings) == {"env": claude_env(run), "skipWebFetchPreflight": True}
    # Web search is a tool of Anthropic's servers.
    assert options.disallowed_tools == ["WebSearch"]


def test_a_guarded_local_run_keeps_the_git_blocks(tmp_path: Path) -> None:
    options = build_options(
        SessionSpec(cwd=tmp_path, permission_mode="default", local=local(context=None)),
        ScriptedHandler(PermissionDecision("allow")),
        tmp_path / "gh",
    )

    assert options.disallowed_tools == [*GIT_WRITE_RULES, "WebSearch"]
    assert options.env is not None
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in options.env


def test_a_subscription_run_has_no_settings_of_its_own(tmp_path: Path) -> None:
    options = build_options(
        SessionSpec(cwd=tmp_path, permission_mode="default"),
        ScriptedHandler(PermissionDecision("allow")),
        tmp_path / "gh",
    )

    assert options.settings is None
    assert options.env is not None
    assert "ANTHROPIC_BASE_URL" not in options.env


async def test_a_local_codex_run_needs_no_login_and_names_its_provider(tmp_path: Path) -> None:
    server = FakeAppServer()
    server.answers["account/read"] = SIGNED_OUT
    run = local()
    spec = SessionSpec(
        cwd=tmp_path,
        permission_mode="default",
        model="qwen/qwen3-coder-30b",
        local=run,
        guard_git=False,
    )

    opened = await provider(tmp_path, server).open(spec, Handler(), RecordingSink())

    [start] = server.requests("thread/start")
    assert start["config"] == codex_config(run)
    assert start["model"] == "qwen/qwen3-coder-30b"
    assert server.requests("account/read") == []
    await opened.send(UserInput("hi"))
    [turn] = server.requests("turn/start")
    assert turn["model"] == "qwen/qwen3-coder-30b"
    await opened.close()
