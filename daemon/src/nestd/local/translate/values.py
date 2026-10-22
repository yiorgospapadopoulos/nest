"""Reading untyped JSON safely: anything of the wrong shape reads as empty."""

from uuid import uuid4

from pydantic import JsonValue

type JsonObject = dict[str, JsonValue]


def obj(value: JsonValue) -> JsonObject:
    return value if isinstance(value, dict) else {}


def items(value: JsonValue) -> list[JsonValue]:
    return value if isinstance(value, list) else []


def objects(value: JsonValue) -> list[JsonObject]:
    return [entry for entry in items(value) if isinstance(entry, dict)]


def string(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


def integer(value: JsonValue) -> int:
    if isinstance(value, bool):
        return 0
    return int(value) if isinstance(value, int | float) else 0


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"
