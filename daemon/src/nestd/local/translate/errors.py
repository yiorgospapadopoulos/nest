"""Error bodies in each agent's own shape, so it shows the server's reason."""

from pydantic import JsonValue, TypeAdapter, ValidationError

from nestd.local.translate.values import JsonObject, obj, string

_MAX_MESSAGE = 1000
_JSON = TypeAdapter[JsonValue](JsonValue)
_ANTHROPIC_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    413: "request_too_large",
    429: "rate_limit_error",
    529: "overloaded_error",
}


def upstream_message(body: bytes) -> str:
    """The reason in a server's error body, whichever common shape it uses."""
    text = body.decode(errors="replace").strip()
    try:
        found = obj(_JSON.validate_json(text))
    except ValidationError:
        found = {}
    error = found.get("error")
    message = (
        string(obj(error).get("message"))
        or string(error)
        or string(found.get("message"))
        or string(found.get("detail"))
    )
    return (message or text or "no details")[:_MAX_MESSAGE]


def anthropic_error(status: int, message: str) -> JsonObject:
    kind = _ANTHROPIC_TYPES.get(status) or (
        "api_error" if status >= 500 else "invalid_request_error"
    )
    return {"type": "error", "error": {"type": kind, "message": message}}


def openai_error(status: int, message: str) -> JsonObject:
    kind = "server_error" if status >= 500 else "invalid_request_error"
    return {"error": {"message": message, "type": kind, "code": None}}
