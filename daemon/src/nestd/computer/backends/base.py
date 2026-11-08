"""The interface every computer-use backend implements (B150)."""

from typing import Protocol

from nestd.computer.models import Action, ActResult, Availability, TargetInfo, TargetKind, View


class Backend(Protocol):
    @property
    def kind(self) -> TargetKind: ...

    async def available(self) -> Availability:
        """Whether this kind can be used here, without starting anything."""
        ...

    async def targets(self) -> list[TargetInfo]:
        """What can be used now."""
        ...

    async def open(self, key: str, url: str | None) -> TargetInfo:
        """Launches, boots or starts the target in the background."""
        ...

    async def view(self, key: str, window: str | None, screenshot: bool) -> View: ...

    async def act(self, key: str, action: Action) -> ActResult:
        """One action. Raises NeedsFront when it only works with the target in front,
        SecureField for a secret field, TargetError otherwise."""
        ...

    async def front(self, key: str) -> None:
        """Brings the target to the front; only after the user allowed it."""
        ...

    async def close(self) -> None:
        """Stops what the backend started for itself, at daemon shutdown."""
        ...
