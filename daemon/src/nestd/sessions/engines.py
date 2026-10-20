"""The agent engines a chat can run on (B91): Claude, the default, and Codex.

A session records its engine by provider name (`claude`, `codex`); sessions from before
B91 are Claude's. Each engine has its own model list, and some lack features Claude has,
which the API refuses with 409 `unsupported_feature` (`ProviderFeature`).
"""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from nestd.errors import InvalidInputError
from nestd.providers.base import AgentProvider, ModelOption, ProviderFeature
from nestd.sessions.errors import UnsupportedFeatureError
from nestd.sessions.models import NewSession

# The engine's entry for a model (None is the engine's default), or None when unknown.
type ModelLookup = Callable[[str | None], Awaitable[ModelOption | None]]
# Raises when the engine cannot take a chat now, such as Codex without a login.
type ReadyCheck = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class Engine:
    provider: AgentProvider
    models: ModelLookup | None = None
    ready: ReadyCheck | None = None

    @property
    def name(self) -> str:
        return self.provider.name

    def supports(self, feature: ProviderFeature) -> bool:
        return feature not in self.provider.unsupported

    def require(self, feature: ProviderFeature) -> None:
        if not self.supports(feature):
            raise UnsupportedFeatureError(self.name, feature)

    async def require_ready(self) -> None:
        if self.ready is not None:
            await self.ready()

    async def find(self, model: str | None) -> ModelOption | None:
        return None if self.models is None else await self.models(model)


class Engines:
    def __init__(self, default: Engine, others: Iterable[Engine] = ()) -> None:
        self.default = default
        self._by_name = {engine.name: engine for engine in (default, *others)}

    def all(self) -> list[Engine]:
        """Every engine, the default first."""
        return list(self._by_name.values())

    def named(self, name: str | None) -> Engine:
        """The engine a new chat asks for; None is the default. 422 for an unknown one."""
        if name is None:
            return self.default
        engine = self._by_name.get(name)
        if engine is None:
            known = ", ".join(sorted(self._by_name))
            msg = f"unknown provider {name!r}; known: {known}"
            raise InvalidInputError(msg)
        return engine

    def of(self, session: NewSession) -> Engine:
        """The session's engine; one not set up here runs on the default."""
        return self.by_name(session.provider)

    def by_name(self, name: str) -> Engine:
        """The engine of that name; one not set up here (Claude's name in tests) is the
        default.
        """
        return self._by_name.get(name, self.default)
