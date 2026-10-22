import json

from nestd.local.run import (
    PLACEHOLDER_KEY,
    LocalRun,
    RunServer,
    claude_env,
    claude_settings,
    codex_config,
    local_run,
)

TRANSLATOR = "http://127.0.0.1:8765/local/ls_1"


def server(*, responses: bool, key: str | None = None) -> RunServer:
    return RunServer(
        id="ls_1",
        base_url="http://127.0.0.1:1234",
        has_responses=responses,
        key=key,
    )


def run_on(*, responses: bool, key: str | None = None, context: int | None = 65536) -> LocalRun:
    return local_run(
        server(responses=responses, key=key),
        model_id="lm_1",
        model="qwen/qwen3-coder-30b",
        context=context,
        vision=False,
        thinking=True,
        port=8765,
        translator_key="tk",
    )


def test_claude_always_goes_through_the_translator_and_codex_direct_when_it_can() -> None:
    run = run_on(responses=True, key="sk")

    assert run == LocalRun(
        model_id="lm_1",
        model="qwen/qwen3-coder-30b",
        context=65536,
        vision=False,
        thinking=True,
        base_url_for_claude=TRANSLATOR,
        key_for_claude="tk",
        base_url_for_codex="http://127.0.0.1:1234/v1",
        key_for_codex="sk",
    )


def test_codex_on_a_server_without_a_key_gets_a_placeholder() -> None:
    run = run_on(responses=True)

    assert (run.key_for_claude, run.key_for_codex) == ("tk", PLACEHOLDER_KEY)


def test_codex_without_the_responses_api_goes_through_the_translator_with_its_key() -> None:
    run = run_on(responses=False, key="sk")

    assert (run.base_url_for_claude, run.key_for_claude) == (TRANSLATOR, "tk")
    assert run.base_url_for_codex == f"{TRANSLATOR}/v1"
    assert run.key_for_codex == "tk"


def test_claude_is_pointed_at_the_translator_for_every_model_it_may_pick() -> None:
    env = claude_env(run_on(responses=False, key="sk"))

    assert env == {
        "ANTHROPIC_BASE_URL": TRANSLATOR,
        "ANTHROPIC_AUTH_TOKEN": "tk",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_MODEL": "qwen/qwen3-coder-30b",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "qwen/qwen3-coder-30b",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "qwen/qwen3-coder-30b",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "qwen/qwen3-coder-30b",
        "CLAUDE_CODE_SUBAGENT_MODEL": "qwen/qwen3-coder-30b",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "65536",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16384",
    }


def test_claude_keeps_a_quarter_of_the_context_for_its_reply_within_limits() -> None:
    def reply_room(context: int) -> str:
        run = local_run(
            server(responses=False),
            model_id="lm_1",
            model="m",
            context=context,
            vision=False,
            thinking=False,
            port=8765,
            translator_key="tk",
        )
        return claude_env(run)["CLAUDE_CODE_MAX_OUTPUT_TOKENS"]

    # Claude Code otherwise keeps 32k for its reply, which a 64k model cannot spare.
    assert reply_room(8192) == "4096"
    assert reply_room(262144) == "32000"


def test_an_unknown_context_is_left_to_claude_code() -> None:
    env = claude_env(run_on(responses=False, context=None))

    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in env
    assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" not in env


def test_the_settings_carry_the_same_environment_and_skip_the_fetch_preflight() -> None:
    run = run_on(responses=False)

    assert json.loads(claude_settings(run)) == {
        "env": claude_env(run),
        "skipWebFetchPreflight": True,
    }


def test_codex_gets_its_own_provider_for_the_thread() -> None:
    config = codex_config(run_on(responses=True, key="sk"))

    assert config == {
        "model_provider": "nestlocal",
        "model_providers.nestlocal.name": "Nest local",
        "model_providers.nestlocal.base_url": "http://127.0.0.1:1234/v1",
        "model_providers.nestlocal.wire_api": "responses",
        "model_providers.nestlocal.http_headers": {"Authorization": "Bearer sk"},
        "model_providers.nestlocal.requires_openai_auth": False,
        "web_search": "disabled",
        "model_context_window": 65536,
    }


def test_codex_without_a_known_context_keeps_its_own() -> None:
    config = codex_config(run_on(responses=True, context=None))

    assert "model_context_window" not in config
