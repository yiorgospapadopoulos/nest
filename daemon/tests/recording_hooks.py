from harness.providers.base import (
    CommandCatalog,
    EngineDetails,
    McpServer,
    ResultInfo,
    UsageInfo,
)
from harness.sessions.models import Session, SessionState


class RecordingHooks:
    def __init__(self) -> None:
        self.states: list[tuple[str, SessionState]] = []
        self.messages: list[str] = []
        self.results: list[tuple[str, ResultInfo]] = []
        self.usages: list[UsageInfo] = []
        self.connectors: list[tuple[str, list[McpServer]]] = []
        self.commands: list[tuple[str, CommandCatalog]] = []
        self.engine: list[EngineDetails] = []
        self.purges: list[str] = []

    async def state_changed(self, session: Session) -> None:
        self.states.append((session.id, session.state))

    async def message(self, session_id: str) -> None:
        self.messages.append(session_id)

    async def turn_result(self, session_id: str, info: ResultInfo) -> None:
        self.results.append((session_id, info))

    async def usage(self, info: UsageInfo) -> None:
        self.usages.append(info)

    async def connectors_reported(self, session_id: str, servers: list[McpServer]) -> None:
        self.connectors.append((session_id, servers))

    async def commands_reported(self, session_id: str, catalog: CommandCatalog) -> None:
        self.commands.append((session_id, catalog))

    async def engine_reported(self, details: EngineDetails) -> None:
        self.engine.append(details)

    async def purged(self, session_id: str) -> None:
        self.purges.append(session_id)
