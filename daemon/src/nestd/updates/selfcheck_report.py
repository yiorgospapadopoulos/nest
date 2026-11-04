"""What `nestd engines selfcheck` prints, read back by whoever started it."""

from pydantic import BaseModel


class EngineCheck(BaseModel):
    id: str
    name: str
    ok: bool
    # The engine's own version; for Claude, Claude Code's.
    version: str | None = None
    detail: str | None = None


class SelfcheckReport(BaseModel):
    ok: bool
    # Whether the daemon's app started and answered its health check.
    daemon: bool
    daemon_detail: str | None = None
    engines: list[EngineCheck]

    def failure(self) -> str:
        """What failed, for the log."""
        failed = [f"{e.id}: {e.detail}" for e in self.engines if not e.ok]
        if not self.daemon:
            failed.insert(0, f"the daemon: {self.daemon_detail}")
        return "; ".join(failed) or "the check failed"
