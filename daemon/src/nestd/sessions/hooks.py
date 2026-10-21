"""What else follows a running session: tracking, reviews, notifications, usage, connectors."""

from typing import Protocol

from nestd.providers.base import (
    CommandCatalog,
    EngineDetails,
    McpServer,
    ResultInfo,
    TokenUsage,
    UsageInfo,
)
from nestd.sessions.models import Session


class SessionHooks(Protocol):
    async def state_changed(self, session: Session) -> None:
        """The session moved to `session.state`; called after the state event."""
        ...

    async def turn_starting(self, session: Session) -> None:
        """A message is about to go to the agent, after the session's running state; a turn
        the agent starts on its own has no such moment (B56).
        """
        ...

    async def message(self, session_id: str) -> None:
        """The agent's transcript grew by a message or task event."""
        ...

    async def turn_result(self, session_id: str, info: ResultInfo) -> None:
        """A turn ended with this result; called before the session's state changes."""
        ...

    async def usage(self, info: UsageInfo, account_id: str | None) -> None:
        """The engine reported the subscription's usage windows, of the account the run
        opened on (B98; None: the engine's active one).
        """
        ...

    async def subagent_usage(self, session_id: str, message_id: str, tokens: TokenUsage) -> None:
        """A subagent's API reply used these tokens; reported again as the reply grows."""
        ...

    async def connectors_reported(self, session_id: str, servers: list[McpServer]) -> None:
        """The session's agent reported its MCP servers and connectors: when it starts
        (mostly still pending) and after each turn (settled).
        """
        ...

    async def commands_reported(self, session_id: str, catalog: CommandCatalog) -> None:
        """The session's agent reported its slash commands and agents."""
        ...

    async def engine_reported(self, details: EngineDetails) -> None:
        """A session's agent reported the engine's models and account (D038)."""
        ...

    async def purged(self, session_id: str) -> None:
        """The session was deleted for good; drop what is kept in memory for it."""
        ...

    async def rewound(self, session: Session, *, conversation: bool, files: bool) -> None:
        """The chat was rewound to before a user message: its transcript from there was
        deleted (`conversation`), its files restored (`files`), or both (B59).
        """
        ...
