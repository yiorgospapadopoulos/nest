from harness.providers.base import McpServer, MessageBlock, ResultInfo, UsageInfo


class RecordingSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def message(self, blocks: list[MessageBlock], parent_tool_use_id: str | None) -> None:
        self.calls.append(("message", (blocks, parent_tool_use_id)))

    async def text_delta(self, text: str) -> None:
        self.calls.append(("text_delta", text))

    async def result(self, info: ResultInfo) -> None:
        self.calls.append(("result", info))

    async def usage(self, info: UsageInfo) -> None:
        self.calls.append(("usage", info))

    async def provider_session_id(self, session_id: str) -> None:
        self.calls.append(("provider_session_id", session_id))

    async def background_tasks(self, running: int) -> None:
        self.calls.append(("background_tasks", running))

    async def connectors(self, servers: list[McpServer]) -> None:
        self.calls.append(("connectors", servers))

    async def stopped(self, error: str) -> None:
        self.calls.append(("stopped", error))
