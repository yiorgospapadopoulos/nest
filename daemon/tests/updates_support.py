"""Fakes for the engine updates' outside world: uv, the registries and the offline check."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx

from nestd.updates.build import PrepareError
from nestd.updates.engines import Versions
from nestd.updates.environments import python_of
from nestd.updates.manifest import Manifest, write_manifest
from nestd.updates.selfcheck_report import EngineCheck, SelfcheckReport

FINGERPRINT = "base-one"
NOW = Versions(
    packages={"claude": "0.2.0", "codex": "0.10.0", "opencode": "1.0.0", "gemini": "0.5.0"},
    shown={"claude": "2.1.0", "codex": "0.10.0", "opencode": "1.0.0", "gemini": "0.5.0"},
)
# The registries' answers when nothing is new.
SAME = {
    "claude-agent-sdk": "0.2.0",
    "openai-codex-cli-bin": "0.10.0",
    "opencode-ai": "1.0.0",
    "@google/gemini-cli": "0.5.0",
}
EDITABLE = "aiohttp==3.14.4\n-e file:///Users/me/My%20Projects/nest/daemon\n"


def make_environment(
    root: Path,
    name: str,
    fingerprint: str = FINGERPRINT,
    packages: Mapping[str, str] | None = None,
    summary: str = "",
) -> Path:
    folder = root / name
    python = python_of(folder)
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    write_manifest(
        folder,
        Manifest(base_fingerprint=fingerprint, packages=packages or NOW.packages, summary=summary),
    )
    return folder


def registry(latest: Mapping[str, str], yanked: Sequence[str] = ()) -> httpx.MockTransport:
    """PyPI and npm answering `latest`; a package not named fails."""

    def answer(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "pypi.org":
            package = path.split("/")[2]
            if package not in latest:
                return httpx.Response(500)
            info = {"version": latest[package], "yanked": package in yanked}
            return httpx.Response(200, json={"info": info})
        package = path.removeprefix("/").removesuffix("/latest")
        if package not in latest:
            return httpx.Response(500)
        return httpx.Response(200, json={"version": latest[package]})

    return httpx.MockTransport(answer)


class FakeUv:
    """Makes the folder `uv venv` would; `fail_on` names a first argument pair that fails."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.freeze = EDITABLE
        self.fail_on: tuple[str, ...] | None = None

    async def __call__(self, args: Sequence[str], cwd: Path, env: Mapping[str, str]) -> str:
        words = list(args)
        self.calls.append(words)
        if self.fail_on is not None and tuple(words[: len(self.fail_on)]) == self.fail_on:
            raise PrepareError("uv failed")
        if words[:2] == ["pip", "freeze"]:
            return self.freeze
        if words[0] == "venv":
            python_of(Path(words[-1])).parent.mkdir(parents=True)
            python_of(Path(words[-1])).write_text("#!/bin/sh\n", encoding="utf-8")
        return ""

    def steps(self) -> list[str]:
        return [" ".join(call[:2]) for call in self.calls]


class FakeSelfcheck:
    """Passes and shows these versions, unless told otherwise."""

    def __init__(self) -> None:
        self.ok = True
        self.shown = {"claude": "2.2.0"}
        self.ran_in: list[Path] = []

    async def __call__(
        self, python: Path, engines_dir: Path, cwd: Path, env: Mapping[str, str]
    ) -> SelfcheckReport:
        self.ran_in.append(python)
        engines = [
            EngineCheck(id=engine, name=engine, ok=self.ok, version=version, detail="broken")
            for engine, version in self.shown.items()
        ]
        return SelfcheckReport(ok=self.ok, daemon=True, engines=engines)


def state_json(path: Path) -> dict[str, object]:
    loaded: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return loaded
