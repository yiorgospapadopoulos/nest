from collections.abc import Sequence
from pathlib import Path

from nestd.gitops.runner import CommandError
from nestd.machine import machine_name


async def test_macos_uses_the_computer_name_for_people() -> None:
    calls: list[tuple[str, ...]] = []

    async def run(argv: Sequence[str], _cwd: Path) -> str:
        calls.append(tuple(argv))
        return "Giorgos's Mac mini\n"

    name = await machine_name(run, platform="darwin", hostname=lambda: "unused")

    assert name == "Giorgos's Mac mini"
    assert calls == [("scutil", "--get", "ComputerName")]


async def test_macos_falls_back_to_the_host_name_when_scutil_fails() -> None:
    async def fails(argv: Sequence[str], _cwd: Path) -> str:
        raise CommandError(argv, 1, "ComputerName: not set")

    name = await machine_name(fails, platform="darwin", hostname=lambda: "mac-mini.local")

    assert name == "mac-mini"


async def test_macos_falls_back_when_scutil_is_missing_or_prints_nothing() -> None:
    async def missing(_argv: Sequence[str], _cwd: Path) -> str:
        raise FileNotFoundError("scutil")

    async def blank(_argv: Sequence[str], _cwd: Path) -> str:
        return "  \n"

    assert await machine_name(missing, platform="darwin", hostname=lambda: "a.local") == "a"
    assert await machine_name(blank, platform="darwin", hostname=lambda: "b") == "b"


async def test_other_systems_use_the_host_name_without_running_anything() -> None:
    calls: list[Sequence[str]] = []

    async def run(argv: Sequence[str], _cwd: Path) -> str:
        calls.append(argv)
        return "unused"

    name = await machine_name(run, platform="linux", hostname=lambda: "build-box.local")

    assert name == "build-box"
    assert calls == []
    # Only a trailing `.local` goes.
    assert await machine_name(run, platform="linux", hostname=lambda: "box.lan") == "box.lan"
