"""Which clients are on screen, so usage probes run only while someone can see the numbers."""

from datetime import datetime, timedelta

from harness.clock import Clock

# Clients report every minute while visible; a report lapses after two missed heartbeats.
HEARTBEAT = timedelta(seconds=60)
VISIBILITY_TTL = 2 * HEARTBEAT + timedelta(seconds=30)


class ClientVisibility:
    """In memory: a daemon restart forgets every client until its next heartbeat."""

    def __init__(self, clock: Clock, ttl: timedelta = VISIBILITY_TTL) -> None:
        self._clock = clock
        self._ttl = ttl
        self._until: dict[str, datetime] = {}

    def report(self, client: str, visible: bool) -> bool:
        """Record a client's report; True when it is the first client to become visible."""
        was_visible = self.any_visible()
        if visible:
            self._until[client] = self._clock.now() + self._ttl
        else:
            self._until.pop(client, None)
        return visible and not was_visible

    def any_visible(self) -> bool:
        now = self._clock.now()
        self._until = {client: until for client, until in self._until.items() if until > now}
        return bool(self._until)
