from datetime import datetime

from pydantic import BaseModel, ConfigDict, JsonValue


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    # None for ephemeral events, which are fanned out live but never stored or replayed.
    id: int | None
    type: str
    ts: datetime
    session_id: str | None
    payload: dict[str, JsonValue]
