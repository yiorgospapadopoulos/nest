"""A JSON-RPC 2.0 client for an engine on the Agent Client Protocol (B107).

ACP is newline-delimited JSON-RPC 2.0 over the agent's stdin and stdout, with the
"jsonrpc" field, and otherwise works as Codex's app-server does: Nest sends requests and
notifications, the agent streams `session/update` notifications and sends requests
(permissions, file reads and writes) that Nest answers. The connection is Codex's client
(`codex_rpc`), named after the engine and sending the field.
"""

from nestd.providers.codex_rpc import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    ClosedHandler,
    CodexClosedError,
    CodexRpc,
    CodexRpcError,
    JsonObject,
    NotificationHandler,
    RequestHandler,
    Transport,
)

__all__ = [
    "AUTH_REQUIRED",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "METHOD_NOT_FOUND",
    "RESOURCE_NOT_FOUND",
    "AcpClosedError",
    "AcpRpc",
    "AcpRpcError",
    "JsonObject",
    "Transport",
]

# ACP's error codes beside JSON-RPC's own.
AUTH_REQUIRED = -32000
RESOURCE_NOT_FOUND = -32002
INVALID_PARAMS = -32602

AcpRpcError = CodexRpcError
AcpClosedError = CodexClosedError


class AcpRpc(CodexRpc):
    def __init__(
        self,
        transport: Transport,
        on_notification: NotificationHandler,
        on_request: RequestHandler,
        on_closed: ClosedHandler | None = None,
        *,
        peer: str = "The engine",
    ) -> None:
        """`peer` is the engine's name, for messages such as "OpenCode ended"."""
        super().__init__(transport, on_notification, on_request, on_closed, peer=peer, jsonrpc=True)
