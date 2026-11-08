"""One chat per target at a time (B150): two agents driving the same app fight."""


class TargetLocks:
    def __init__(self) -> None:
        self._holders: dict[str, str] = {}

    def holder(self, key: str) -> str | None:
        return self._holders.get(key)

    def take(self, key: str, session_id: str) -> bool:
        """True when the chat holds `key` now; False when another chat does."""
        holder = self._holders.setdefault(key, session_id)
        return holder == session_id

    def held_by(self, session_id: str) -> list[str]:
        return [key for key, holder in self._holders.items() if holder == session_id]

    def release(self, key: str, session_id: str) -> None:
        if self._holders.get(key) == session_id:
            del self._holders[key]

    def release_all(self, session_id: str) -> list[str]:
        keys = self.held_by(session_id)
        for key in keys:
            del self._holders[key]
        return keys
