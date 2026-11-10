"""Origin check for cookie logins (B159 R07): a page on another host of the same site (the
tailnet) can make a paired browser send its cookie, so a cookie-authenticated request that
changes something must come from Nest's own page. Bearer requests and sockets are left
alone; the Host check runs first.
"""

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from nestd.api.deps import COOKIE_NAME, LEGACY_COOKIE_NAME

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CookieOriginMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not cookie_request_allowed(
            scope["method"], Headers(scope=scope)
        ):
            await PlainTextResponse("Cross-site request refused", status_code=403)(
                scope, receive, send
            )
            return
        await self._app(scope, receive, send)


def cookie_request_allowed(method: str, headers: Headers) -> bool:
    if method.upper() in SAFE_METHODS or not _cookie_login(headers):
        return True
    if headers.get("sec-fetch-site") == "same-origin":
        return True
    origin, host = headers.get("origin"), headers.get("host")
    # Scheme left out: `tailscale serve` takes https and passes the request on as http.
    return bool(origin and host) and urlsplit(origin).netloc.lower() == (host or "").lower()


def _cookie_login(headers: Headers) -> bool:
    """Whether the request authenticates with a cookie, as `deps.authenticated_device`
    does when there is no Bearer token."""
    if headers.get("authorization", "").partition(" ")[0].lower() == "bearer":
        return False
    cookies = cookie_parser(headers.get("cookie", ""))
    return bool(cookies.get(COOKIE_NAME) or cookies.get(LEGACY_COOKIE_NAME))
