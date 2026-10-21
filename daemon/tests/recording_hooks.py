from nestd.providers.base import (
    CommandCatalog,
    EngineDetails,
    McpServer,
    ResultInfo,
    TokenUsage,
    UsageInfo,
)
from nestd.sessions.models import Session, SessionState


class RecordingHooks:
    def __init__(self) -> None:
        self.states: list[tuple[str, SessionState]] = []
        self.messages: list[str] = []
        self.results: list[tuple[str, ResultInfo]] = []
        self.usages: list[UsageInfo] = []
        # The account each usage report was for (B98); None without accounts.
        self.usage_accounts: list[str | None] = []
        self.subagent_usages: list[tuple[str, str, TokenUsage]] = []
        self.connectors: list[tuple[str, list[McpServer]]] = []
        self.commands: list[tuple[str, CommandCatalog]] = []
        self.engine: list[EngineDetails] = []
        self.purges: list[str] = []
        self.starts: list[tuple[str, SessionState]] = []
        self.rewinds: list[tuple[str, bool, bool]] = []

    async def state_changed(self, session: Session) -> None:
        self.states.append((session.id, session.state))

    async def turn_starting(self, session: Session) -> None:
        self.starts.append((session.id, session.state))

    async def message(self, session_id: str) -> None:
        self.messages.append(session_id)

    async def turn_result(self, session_id: str, info: ResultInfo) -> None:
        self.results.append((session_id, info))

    async def usage(self, info: UsageInfo, account_id: str | None) -> None:
        self.usages.append(info)
        self.usage_accounts.append(account_id)

    async def subagent_usage(self, session_id: str, message_id: str, tokens: TokenUsage) -> None:
        self.subagent_usages.append((session_id, message_id, tokens))

    async def connectors_reported(self, session_id: str, servers: list[McpServer]) -> None:
        self.connectors.append((session_id, servers))

    async def commands_reported(self, session_id: str, catalog: CommandCatalog) -> None:
        self.commands.append((session_id, catalog))

    async def engine_reported(self, details: EngineDetails) -> None:
        self.engine.append(details)

    async def purged(self, session_id: str) -> None:
        self.purges.append(session_id)

    async def rewound(self, session: Session, *, conversation: bool, files: bool) -> None:
        self.rewinds.append((session.id, conversation, files))
