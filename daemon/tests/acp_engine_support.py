"""Fakes for the ACP engines' outside world in the daemon's wiring (B107): npm, the engine
process and its install folder. The in-memory engine itself is `acp_support`.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

from nestd.engine.acp import AcpSetup
from nestd.engine.acp_install import NpmError, installed_program, platform_names
from nestd.engine.acp_registry import platform_name
from nestd.providers.acp_engines import ACP_ENGINES, AcpEngine
from nestd.providers.acp_process import AcpLaunch, AcpTransportFactory
from nestd.providers.base import ModelOption
from nestd.providers.codex_rpc import Transport

FREE_MODELS = [
    ModelOption(
        value="default",
        display_name="Default",
        description="",
        resolved_model="opencode/big-pickle",
    ),
    ModelOption(value="opencode/big-pickle", display_name="Big Pickle", description=""),
]


class FakeNpm:
    """Installs by making the package's program file, as npm would put it."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path, dict[str, str]]] = []
        self.failure: str | None = None

    async def __call__(self, args: Sequence[str], cwd: Path, env: Mapping[str, str]) -> None:
        self.calls.append((list(args), cwd, dict(env)))
        if self.failure is not None:
            raise NpmError(self.failure)
        prefix = Path(args[list(args).index("--prefix") + 1])
        package = args[-1].rsplit("@", 1)[0]
        engine = next(engine for engine in ACP_ENGINES if engine.package == package)
        program = program_path(engine, prefix)
        program.parent.mkdir(parents=True, exist_ok=True)
        program.write_text("#!/bin/sh\n", encoding="utf-8")

    def installs(self) -> list[str]:
        return [args[-1] for args, _cwd, _env in self.calls]


def program_path(engine: AcpEngine, prefix: Path) -> Path:
    """Where the engine's real program lands in an npm prefix on this machine."""
    if engine.delivery == "download":
        return prefix / engine.downloads[platform_name()].program
    os_name, arch = platform_names()
    if engine.package == "opencode-ai":
        return prefix / "node_modules" / f"opencode-{os_name}-{arch}" / "bin" / engine.executable
    if engine.package == "@github/copilot":
        return prefix / "node_modules" / "@github" / f"copilot-{os_name}-{arch}" / "copilot"
    if engine.package == "@xai-official/grok":
        platform = f"grok-{os_name}-{arch}"
        return prefix / "node_modules" / "@xai-official" / platform / "bin" / engine.executable
    return prefix / "node_modules" / ".bin" / engine.executable


def preinstall(engines_dir: Path, engine: AcpEngine) -> Path:
    """The engine's pinned version, as if installed earlier."""
    assert engine.version is not None
    path = program_path(engine, engines_dir / engine.id / engine.version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    assert installed_program(engine, engines_dir / engine.id / engine.version) == path
    return path


async def no_engine_process(launch: AcpLaunch, cwd: Path) -> Transport:
    """Never a real engine: a test that gets here needed a fake probe or provider."""
    msg = f"no engine process in tests ({launch.args[0]} in {cwd})"
    raise OSError(msg)


def acp_setup(
    tmp_path: Path, npm: FakeNpm | None = None, transport: AcpTransportFactory | None = None
) -> AcpSetup:
    """No real npm, engine, PATH or home; `transport` is an in-memory engine to run."""
    return AcpSetup(
        npm=npm or FakeNpm(),
        transport=transport or no_engine_process,
        base_env={"PATH": str(tmp_path / "no-bin")},
        home=tmp_path / "home",
    )
