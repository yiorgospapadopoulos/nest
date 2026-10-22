"""Chats on local models (B106): a session keeps its engine as `provider` and names the
model `local:<id>`; each run is pointed at the model's server.
"""

from collections.abc import Awaitable, Callable, Iterable
from typing import Protocol

from pydantic import JsonValue

from nestd.attachments.store import Attachment
from nestd.local.errors import LocalUnsupportedError
from nestd.local.models import is_local
from nestd.local.run import LocalRun
from nestd.providers.base import TokenUsage

NO_IMAGES = "This local model cannot read images. Choose a model with vision, or remove the image."


class LocalSource(Protocol):
    async def engine(self) -> str:
        """The engine new local chats run on."""
        ...

    async def require_running(self, model: str) -> None:
        """409 `local_server_down` when the model's server does not answer."""
        ...

    async def run_for(self, model: str) -> LocalRun: ...

    async def load_model(self, model: str, notice: Callable[[str], Awaitable[None]]) -> None:
        """Have the model's app load it for the run, saying so through `notice` when it
        does; raises when it cannot.
        """
        ...

    async def down(self, model: str) -> dict[str, JsonValue] | None:
        """The details of a server that does not answer now; None when it does."""
        ...

    async def record_usage(self, model: str, tokens: TokenUsage) -> None:
        """A local turn's tokens, by the local model's id."""
        ...


class NoLocalModelsError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("this daemon runs no local models")


def require(local: LocalSource | None) -> LocalSource:
    """The local models, for a chat that names one."""
    if local is None:
        raise NoLocalModelsError
    return local


def crosses_local(before: str | None, after: str | None) -> bool:
    """Whether a model change moves a run to or from a local model, or between two: its
    endpoint changes, so a new run is needed.
    """
    return before != after and (is_local(before) or is_local(after))


async def require_features(
    local: LocalSource | None, model: str | None, attachments: Iterable[Attachment]
) -> None:
    """409 `unsupported_feature` for an image sent to a local model without vision."""
    if not is_local(model) or not any(a.is_image for a in attachments):
        return
    if not (await require(local).run_for(model)).vision:
        raise LocalUnsupportedError("images", NO_IMAGES)
