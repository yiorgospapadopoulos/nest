"""`nestd engines selfcheck`: can this environment run the daemon and its engines?

Run with an environment's own Python before it is offered. Everything happens under a
throwaway home: data, config, Claude's and Codex's folders, with an in-memory secret store
and no API keys or login, so it cannot reach the user's data or accounts. The daemon's app
is built and started without binding a port and asked for its health. Each engine is
started and answers its handshake (Claude Code's and Codex's `initialize`, ACP's
`initialize` and `session/new`); nothing is sent to a model. Claude Code also points at a
closed local port, so even a call nobody asked for could not leave the machine, and finds
a stand-in for macOS's `security` first on its PATH, since it looks for its login in the
Keychain that way. An engine that wants a sign-in but answers counts as a pass: a throwaway
home has none.

Environment variables are replaced for the whole process, which only runs this.
"""

import asyncio
import os
import re
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import claude_agent_sdk
import httpx
from claude_agent_sdk import ClaudeSDKClient

from nestd.api.app import create_app
from nestd.clock import SystemClock
from nestd.context import AppContext
from nestd.engine.acp_install import installed_program
from nestd.engine.fetch import info_options
from nestd.paths import AppPaths
from nestd.platform import Platform
from nestd.providers.acp import probe
from nestd.providers.acp_engines import AcpEngine
from nestd.providers.acp_process import AcpLaunch
from nestd.providers.codex_engine import ask_codex, read_login
from nestd.providers.codex_process import app_server_launch, bundled_binary, spawn
from nestd.providers.shell_env import no_shell_env
from nestd.updates.engines import followed_engines, npm_engines
from nestd.updates.selfcheck_report import EngineCheck, SelfcheckReport

_HANDSHAKE_LIMIT = timedelta(seconds=60)
_VERSION_LIMIT = 30.0
_VERSION = re.compile(r"\d+\.\d+[\w.+-]*")
# Nothing listens there; a port below 1024 is never given out to a client either.
_CLOSED_PORT_URL = "http://127.0.0.1:9"
_SECRET_NAME = re.compile(r"(_API_KEY|_TOKEN)$")
# `security`'s own exit code for an item that is not in the Keychain.
_NO_KEYCHAIN = "#!/bin/sh\nexit 44\n"


class MemorySecretStore:
    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def get(self, account: str) -> str | None:
        return self._items.get(account)

    def set(self, account: str, value: str) -> None:
        self._items[account] = value

    def delete(self, account: str) -> None:
        self._items.pop(account, None)


def scratch_env(env: Mapping[str, str], root: Path) -> dict[str, str]:
    """`env` with every place Nest and the engines keep things under `root`, and no keys."""
    kept = {name: value for name, value in env.items() if not _SECRET_NAME.search(name)}
    return {
        **kept,
        "PATH": os.pathsep.join((str(root / "bin"), env.get("PATH", ""))),
        "HOME": str(root / "home"),
        "NEST_DATA_DIR": str(root / "data"),
        "NEST_CONFIG_DIR": str(root / "config"),
        "CLAUDE_CONFIG_DIR": str(root / "claude"),
        "CODEX_HOME": str(root / "codex"),
        "XDG_DATA_HOME": str(root / "xdg-data"),
        "XDG_STATE_HOME": str(root / "xdg-state"),
        "XDG_CONFIG_HOME": str(root / "xdg-config"),
        "XDG_CACHE_HOME": str(root / "xdg-cache"),
        "ANTHROPIC_BASE_URL": _CLOSED_PORT_URL,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_TELEMETRY": "1",
    }


def run_selfcheck_here(engines_dir: Path, platform: Platform) -> SelfcheckReport:
    with tempfile.TemporaryDirectory(prefix="nest-check-", ignore_cleanup_errors=True) as folder:
        root = Path(folder).resolve()
        scratch = scratch_env(os.environ, root)
        os.environ.clear()
        os.environ.update(scratch)
        for name in ("HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME"):
            Path(scratch[name]).mkdir()
        _stand_in_for_keychain(root / "bin")
        return asyncio.run(_check_everything(engines_dir, Path(scratch["HOME"]), platform))


def _stand_in_for_keychain(folder: Path) -> None:
    folder.mkdir()
    program = folder / "security"
    program.write_text(_NO_KEYCHAIN, encoding="utf-8")
    program.chmod(0o755)


async def _check_everything(engines_dir: Path, home: Path, platform: Platform) -> SelfcheckReport:
    daemon_detail = await _check_daemon(home, platform)
    names = {engine.id: engine.name for engine in followed_engines()}
    engines = [
        await _guarded("claude", names["claude"], lambda: _check_claude(home)),
        await _guarded("codex", names["codex"], _check_codex),
    ]
    for engine in npm_engines():
        checked = await _guarded(
            engine.id, engine.name, lambda e=engine: _check_acp(e, engines_dir, home)
        )
        engines.append(checked)
    daemon = daemon_detail is None
    return SelfcheckReport(
        ok=daemon and all(engine.ok for engine in engines),
        daemon=daemon,
        daemon_detail=daemon_detail,
        engines=engines,
    )


async def _guarded(
    engine_id: str, name: str, check: Callable[[], Awaitable[str | None]]
) -> EngineCheck:
    """`check` gives the engine's version; any failure is that engine's result."""
    try:
        version = await check()
    except Exception as error:
        # Only the kind: an engine's message may quote its environment.
        return EngineCheck(id=engine_id, name=name, ok=False, detail=type(error).__name__)
    return EngineCheck(id=engine_id, name=name, ok=True, version=version)


async def _check_daemon(home: Path, platform: Platform) -> str | None:
    """Why the daemon could not start, None when it answered. No socket: the app is called
    in-process.
    """
    try:
        paths = replace(AppPaths.from_env(os.environ, home, platform), token_socket=None)
        ctx = await AppContext.build(
            paths, MemorySecretStore(), SystemClock(), shell_env=no_shell_env, platform=platform
        )
        try:
            app = create_app(ctx, restart=lambda: None, loops=False)
            transport = httpx.ASGITransport(app=app)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client,
            ):
                response = await client.get("/api/health")
        finally:
            await ctx.close()
    except Exception as error:
        return type(error).__name__
    return None if response.status_code == 200 else f"health answered {response.status_code}"


async def _program_version(*args: str) -> str:
    """The version a program prints for `--version`, whatever words surround it."""
    process = await asyncio.create_subprocess_exec(
        *args,
        "--version",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(_VERSION_LIMIT):
            stdout, _ = await process.communicate()
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    found = _VERSION.search(stdout.decode(errors="replace"))
    if process.returncode != 0 or found is None:
        msg = f"{args[0]} gave no version"
        raise RuntimeError(msg)
    return found.group()


async def _check_claude(home: Path) -> str:
    """The SDK's own Claude Code, connected as `engine/fetch.py` reads its models: the
    initialize handshake only, on a home with no login.
    """
    program = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    version = await _program_version(str(program))
    options = replace(info_options(home), cli_path=program)
    client = ClaudeSDKClient(options)
    try:
        async with asyncio.timeout(_HANDSHAKE_LIMIT.total_seconds()):
            await client.connect()
            if await client.get_server_info() is None:
                msg = "Claude Code answered nothing"
                raise RuntimeError(msg)
    finally:
        with suppress(Exception):
            await client.disconnect()
    return version


async def _check_codex() -> str:
    binary = bundled_binary()
    version = await _program_version(str(binary.executable))
    launch = app_server_launch(binary, os.environ, Path(os.environ["CODEX_HOME"]))
    await ask_codex(spawn, launch, read_login, _HANDSHAKE_LIMIT)
    return version


async def _check_acp(engine: AcpEngine, engines_dir: Path, home: Path) -> str | None:
    if not (engines_dir / engine.id).is_dir():
        return None
    program = installed_program(engine, engines_dir / engine.id / (engine.version or ""))
    if program is None:
        msg = f"{engine.id} {engine.version} is not installed"
        raise RuntimeError(msg)
    launch = AcpLaunch(args=(str(program), *engine.args), env={**os.environ, **engine.env})
    found = await probe(launch, home)
    return found.agent_version or engine.version
