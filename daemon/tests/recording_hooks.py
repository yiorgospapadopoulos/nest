from harness.providers.base import McpServer, ResultInfo, UsageInfo
from harness.sessions.models import Session, SessionState


class RecordingHooks:
    def __init__(self) -> None:
        self.states: list[tuple[str, SessionState]] = []
        self.messages: list[str] = []
        self.results: list[tuple[str, ResultInfo]] = []
        self.usages: list[UsageInfo] = []
        self.connectors: list[tuple[str, list[McpServer]]] = []

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
