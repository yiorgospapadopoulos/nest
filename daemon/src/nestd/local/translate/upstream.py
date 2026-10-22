"""Where the translator sends a server's requests; given by the app's `resolve`."""

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Upstream:
    base_url: str
    # The server's own key, from the Keychain.
    key: str | None
    # The server speaks Anthropic Messages itself, so Claude Code's requests pass through.
    messages: bool
    # Its Messages usage counts cache reads inside input_tokens (LM Studio 0.4).
    usage_counts_cache: bool = False
    # The app serving it, such as "LM Studio", named when its context is too small.
    app: str | None = None
    # The context each model (by the server's id) is loaded with, where known.
    contexts: Mapping[str, int] = field(default_factory=dict[str, int])
