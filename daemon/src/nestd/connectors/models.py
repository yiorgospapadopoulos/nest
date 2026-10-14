from datetime import datetime

from pydantic import BaseModel

from nestd.connectors.naming import ConnectorGroup, ManageHint


class Connector(BaseModel):
    # The server name as Claude Code reports it.
    name: str
    display_name: str
    group: ConnectorGroup
    # connected, needs-auth, failed, pending, or whatever else Claude Code reports.
    status: str
    # Why it failed, when Claude Code says.
    error: str | None
    manage_hint: ManageHint
    # The session whose agent last reported it.
    source: str
    last_seen_at: datetime
