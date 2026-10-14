"""Starts the modules enabled in settings and stops them in reverse order."""

from collections.abc import Callable, Iterable, Mapping
from typing import Protocol

from nestd.config.errors import ConfigError


class Module[C](Protocol):
    @property
    def name(self) -> str: ...

    async def start(self, ctx: C) -> None: ...

    async def stop(self) -> None: ...


class ModuleRegistry[C]:
    def __init__(self, factories: Mapping[str, Callable[[], Module[C]]]) -> None:
        self._factories = factories
        self._started: list[Module[C]] = []

    @property
    def started(self) -> list[str]:
        return [module.name for module in self._started]

    async def start_enabled(self, enabled: Iterable[str], ctx: C) -> None:
        names = list(dict.fromkeys(enabled))
        unknown = sorted(set(names) - self._factories.keys())
        if unknown:
            msg = f"unknown modules: {', '.join(unknown)}"
            raise ConfigError(msg)
        for name in names:
            module = self._factories[name]()
            await module.start(ctx)
            self._started.append(module)

    async def stop_all(self) -> None:
        while self._started:
            await self._started.pop().stop()
