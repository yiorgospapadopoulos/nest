from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


class Device(BaseModel):
    id: str
    name: str
    is_local: bool
    created_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True)
class PairingCode:
    code: str
    expires_at: datetime
