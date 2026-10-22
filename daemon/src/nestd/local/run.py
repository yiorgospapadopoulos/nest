"""Where one run on a local model goes (B106), and how each engine is pointed there for that
run only, never through the user's settings.

Claude Code needs the Anthropic Messages API and Codex the OpenAI Responses API. Claude
Code always goes through Nest's proxy at `/local/<server id>` on the daemon: it passes the
requests to a server's own Messages API with one fix (see `translate.anthropic_native`), or
translates them to its Chat Completions. Codex goes there only for a server without the
Responses API. The engines send the proxy the daemon's translator key (made at start,
never stored); it sends the server its own key.
"""

import json
from dataclasses import dataclass

from pydantic import JsonValue

# What Codex and the proxy send a server that takes no key. Claude always gets the
# translator key: without a key of its own it would send the user's subscription token.
PLACEHOLDER_KEY = "nest-local"
CODEX_PROVIDER = "nestlocal"
# The room Claude Code keeps for its reply on a local model: a quarter of the context,
# within these bounds (its own default is 32k).
REPLY_MIN = 4096
REPLY_MAX = 32000


@dataclass(frozen=True)
class RunServer:
    id: str
    base_url: str
    has_responses: bool
    # The server's own key, from the Keychain.
    key: str | None


@dataclass(frozen=True)
class LocalRun:
    model_id: str
    # The server's id for the model.
    model: str
    context: int | None
    vision: bool
    thinking: bool
    base_url_for_claude: str
    key_for_claude: str
    base_url_for_codex: str
    key_for_codex: str


def translator_url(port: int, server_id: str) -> str:
    return f"http://127.0.0.1:{port}/local/{server_id}"


def local_run(
    server: RunServer,
    *,
    model_id: str,
    model: str,
    context: int | None,
    vision: bool,
    thinking: bool,
    port: int,
    translator_key: str,
) -> LocalRun:
    translator = translator_url(port, server.id)
    own_key = server.key or PLACEHOLDER_KEY
    return LocalRun(
        model_id=model_id,
        model=model,
        context=context,
        vision=vision,
        thinking=thinking,
        base_url_for_claude=translator,
        key_for_claude=translator_key,
        base_url_for_codex=f"{server.base_url if server.has_responses else translator}/v1",
        key_for_codex=own_key if server.has_responses else translator_key,
    )


def claude_env(run: LocalRun) -> dict[str, str]:
    """Every model name Claude Code may pick, its subagents' included, is the server's
    model; nothing goes to Anthropic.
    """
    env = {
        "ANTHROPIC_BASE_URL": run.base_url_for_claude,
        "ANTHROPIC_AUTH_TOKEN": run.key_for_claude,
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_MODEL": run.model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": run.model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": run.model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": run.model,
        "CLAUDE_CODE_SUBAGENT_MODEL": run.model,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
    }
    if run.context is not None:
        # Else Claude Code assumes 200K for a model it does not know.
        env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(run.context)
        # Else it keeps 32k of the context for its reply, which a 64k model cannot spare.
        reply = min(max(run.context // 4, REPLY_MIN), REPLY_MAX)
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(reply)
    return env


def claude_settings(run: LocalRun) -> str:
    """The run's `--settings`: their `env` beats one in the user's settings.json, which the
    process environment does not (spike).
    """
    return json.dumps({"env": claude_env(run), "skipWebFetchPreflight": True})


def codex_config(run: LocalRun) -> dict[str, JsonValue]:
    """`thread/start` config keys for a provider of the run's own; no login needed."""
    prefix = f"model_providers.{CODEX_PROVIDER}"
    config: dict[str, JsonValue] = {
        "model_provider": CODEX_PROVIDER,
        f"{prefix}.name": "Nest local",
        f"{prefix}.base_url": run.base_url_for_codex,
        f"{prefix}.wire_api": "responses",
        f"{prefix}.http_headers": {"Authorization": f"Bearer {run.key_for_codex}"},
        f"{prefix}.requires_openai_auth": False,
        # Web search runs on OpenAI's servers, not the local one (spike: drops the tool).
        "web_search": "disabled",
    }
    if run.context is not None:
        config["model_context_window"] = run.context
    return config
