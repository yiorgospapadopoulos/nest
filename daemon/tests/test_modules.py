from collections.abc import Callable

import pytest

from harness.config.errors import ConfigError
from harness.modules.registry import Module, ModuleRegistry


class RecordingModule:
    def __init__(self, name: str, log: list[str]) -> None:
        self.name = name
        self._log = log

    async def start(self, ctx: str) -> None:
        self._log.append(f"start {self.name} {ctx}")

    async def stop(self) -> None:
        self._log.append(f"stop {self.name}")


def factory(name: str, log: list[str]) -> Callable[[], Module[str]]:
    def build() -> Module[str]:
        log.append(f"build {name}")
        return RecordingModule(name, log)

    return build


async def test_only_enabled_modules_are_built_and_started_in_order() -> None:
    log: list[str] = []
    registry = ModuleRegistry[str]({n: factory(n, log) for n in ("a", "b", "c")})

    await registry.start_enabled(["c", "a", "c"], "ctx")

    assert log == ["build c", "start c ctx", "build a", "start a ctx"]
    assert registry.started == ["c", "a"]


async def test_stop_all_runs_in_reverse_start_order_once() -> None:
    log: list[str] = []
    registry = ModuleRegistry[str]({n: factory(n, log) for n in ("a", "b")})
    await registry.start_enabled(["a", "b"], "ctx")
    log.clear()

    await registry.stop_all()
    await registry.stop_all()

    assert log == ["stop b", "stop a"]
    assert registry.started == []


async def test_unknown_modules_are_a_config_error_before_anything_starts() -> None:
    log: list[str] = []
    registry = ModuleRegistry[str]({"a": factory("a", log)})

    with pytest.raises(ConfigError, match="unknown modules: nope, zzz"):
        await registry.start_enabled(["a", "zzz", "nope"], "ctx")

    assert log == []
