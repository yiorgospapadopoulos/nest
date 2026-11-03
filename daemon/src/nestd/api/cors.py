"""CORS for the desktop app (B117): its page, bundled in the app, calls the API from its
own origin with a Bearer token. Only those origins and the ones in `[server]
allowed_origins` get CORS headers; there is no credentials mode, so a cookie never
authenticates a cross-origin request. A preflight is answered here, before any route,
so it needs no token.
"""

from collections.abc import Callable, Sequence

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The page's origin in the desktop app: Linux and macOS, then Windows.
DESKTOP_ORIGINS = ("tauri://localhost", "http://tauri.localhost")
ALLOWED_METHODS = "GET, POST, PUT, PATCH, DELETE"
ALLOWED_HEADERS = "Authorization, Content-Type"
MAX_AGE_SECONDS = "600"


def normalized_origin(origin: str) -> str:
    return origin.rstrip("/").lower()


def cors_origin_allowed(origin: str, extra: Sequence[str]) -> bool:
    normalized = normalized_origin(origin)
    return normalized in DESKTOP_ORIGINS or normalized in (
        normalized_origin(entry) for entry in extra
    )


class DesktopCorsMiddleware:
    def __init__(self, app: ASGIApp, allowed: Callable[[], Sequence[str]]) -> None:
        self._app = app
        # Read per request, so a reloaded settings file applies at once.
        self._allowed = allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin is None or not cors_origin_allowed(origin, self._allowed()):
            await self._app(scope, receive, send)
            return
        if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
            await self._preflight(origin, headers)(scope, receive, send)
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["Access-Control-Allow-Origin"] = origin
                response_headers.add_vary_header("Origin")
            await send(message)

        await self._app(scope, receive, send_with_cors)

    @staticmethod
    def _preflight(origin: str, request: Headers) -> Response:
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": ALLOWED_METHODS,
            "Access-Control-Allow-Headers": ALLOWED_HEADERS,
            "Access-Control-Max-Age": MAX_AGE_SECONDS,
            "Vary": "Origin",
        }
        # WebView2 asks before a page reaches a loopback address (Private Network Access).
        if request.get("access-control-request-private-network") == "true":
            headers["Access-Control-Allow-Private-Network"] = "true"
        return Response(status_code=204, headers=headers)
