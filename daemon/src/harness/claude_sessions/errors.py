from pydantic import JsonValue

from harness.errors import ConflictError, NotFoundError

OPEN_ELSEWHERE_CODE = "open_in_claude_code"


class ClaudeChatNotFoundError(NotFoundError):
    pass


class ChatOpenElsewhereError(ConflictError):
    """Two processes writing one transcript would interleave and corrupt the chat."""

    def __init__(self) -> None:
        super().__init__("This chat is open in Claude Code right now. Close it there first.")

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": OPEN_ELSEWHERE_CODE}
