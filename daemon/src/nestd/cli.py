"""Command line entry point.

`nestd serve | service install|uninstall|status|check-secrets|wait | pair |
design generate|check|icon | gates changed|record | engines install|selfcheck`.
"""

import argparse
import asyncio
import logging
import os
import tempfile
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path

import httpx

from nestd import __version__
from nestd.accounts.profiles import drop_leaked_env
from nestd.api.app import create_app
from nestd.auth.devices import LOCAL_DEVICE_ACCOUNT
from nestd.auth.models import PairingCode
from nestd.auth.secrets import SecretStoreUnavailableError
from nestd.config.errors import ConfigError
from nestd.config.loader import load_settings
from nestd.context import AppContext
from nestd.design.errors import DesignError
from nestd.design.icon import generate_icons
from nestd.design.loader import find_root
from nestd.design.outputs import generate, stale_outputs
from nestd.engine import acp_registry
from nestd.engine.acp_install import EngineInstall, run_npm
from nestd.folder_move import (
    LEGACY_DB_NAME,
    FolderMoveError,
    adopt_legacy_database,
    legacy_moves,
    move_folder,
)
from nestd.gates.changes import changed_paths, merge_base, repository_root
from nestd.gates.errors import GatesError
from nestd.gates.rules import ALL_PARTS, Selection, select
from nestd.logging_setup import configure_logging
from nestd.paths import AppPaths, is_packaged
from nestd.perf.gate_times import GateRun, GateTimes, stage_times
from nestd.providers.acp import sign_in
from nestd.providers.acp_engines import ACP_ENGINES
from nestd.providers.acp_process import AcpLaunch
from nestd.providers.acp_rpc import AcpRpcError
from nestd.providers.shell_env import LoginShellEnv, login_shell
from nestd.runtime import Runtime, default_runtime
from nestd.service.base import ServiceError, ServiceManager
from nestd.service.launchd import LEGACY_LABEL
from nestd.service.manager import service_manager
from nestd.service.restart import Restarter
from nestd.storage.errors import DatabaseError
from nestd.updates.app import note_start, note_stop
from nestd.updates.boot import SWITCHED_ENV, Boot, TrialWatch, switch_environment
from nestd.updates.selfcheck import run_selfcheck_here
from nestd.updates.service import answers_health

type Handler = Callable[[argparse.Namespace, AppPaths, Runtime], int]

logger = logging.getLogger(__name__)

SERVICE_WAIT_SECONDS = 90
# A keyring locked at start is asked this often, this far apart (B136).
KEYRING_TRIES = 10
KEYRING_WAIT_SECONDS = 2.0


def main(argv: list[str] | None = None, runtime: Runtime | None = None) -> int:
    rt = runtime or default_runtime()
    args = _parser().parse_args(argv)
    handler: Handler = args.handler
    try:
        return handler(args, AppPaths.from_env(rt.env, rt.home, rt.platform), rt)
    except (
        ConfigError,
        DatabaseError,
        DesignError,
        FolderMoveError,
        GatesError,
        SecretStoreUnavailableError,
        ServiceError,
    ) as error:
        print(f"nestd: {error}", file=rt.err)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nestd", description="Nest daemon (nestd)")
    commands = parser.add_subparsers(required=True, metavar="command")

    serve = commands.add_parser("serve", help="run the daemon in the foreground")
    serve.add_argument("--port", type=int, help="override the port from settings.toml")
    serve.set_defaults(handler=_serve)

    service = commands.add_parser(
        "service", help="manage the background service (launchd on macOS, systemd on Linux)"
    )
    actions = service.add_subparsers(required=True, metavar="action")
    for name, handler, help_text in (
        ("install", _service_install, "install and start the service"),
        ("uninstall", _service_uninstall, "stop and remove the service"),
        ("status", _service_status, "show whether the service is installed and loaded"),
        (
            "check-secrets",
            _service_check_secrets,
            "fail if the system's secret store cannot be read",
        ),
        ("wait", _service_wait, "wait until the daemon answers its health check"),
    ):
        actions.add_parser(name, help=help_text).set_defaults(handler=handler)

    pair = commands.add_parser("pair", help="create a one-time code to pair a device")
    pair.set_defaults(handler=_pair)

    design = commands.add_parser("design", help="generate the client design token files")
    design_actions = design.add_subparsers(required=True, metavar="action")
    for name, handler, help_text in (
        ("generate", _design_generate, "write the CSS, Swift and mascot files from design/"),
        ("check", _design_check, "fail if the generated token files are missing or stale"),
        ("icon", _design_icon, "write the app icon PNGs from the icon pixie's sprite"),
    ):
        action = design_actions.add_parser(name, help=help_text)
        action.add_argument("--root", type=Path, help="repository root (default: found upward)")
        action.set_defaults(handler=handler)

    gates = commands.add_parser("gates", help="pick the quality gates a change needs")
    gates_actions = gates.add_subparsers(required=True, metavar="action")
    changed = gates_actions.add_parser(
        "changed",
        help="print the parts (daemon web apple) changed since the merge base with --base",
    )
    changed.add_argument("--base", default="main", help="base ref (default: main)")
    changed.add_argument("--root", type=Path, help="repository root (default: from git)")
    changed.set_defaults(handler=_gates_changed)
    record = gates_actions.add_parser(
        "record",
        help="add a passing check's times to gate-times.jsonl in Nest's data folder",
    )
    record.add_argument("--total", type=int, required=True, help="the whole check, in ms")
    record.add_argument(
        "stages", nargs="+", metavar="part=ms", help="one per stage; summed per part"
    )
    record.set_defaults(handler=_gates_record)

    engines = commands.add_parser("engines", help="manage the engines Nest installs itself")
    engines_actions = engines.add_subparsers(required=True, metavar="action")
    engines_actions.add_parser(
        "install", help="install every bundled engine's pinned version that is missing"
    ).set_defaults(handler=_engines_install)
    selfcheck = engines_actions.add_parser(
        "selfcheck",
        help="check offline, on throwaway folders, that this environment runs the daemon and "
        "its engines; prints JSON",
    )
    selfcheck.add_argument(
        "--engines-dir", type=Path, help="where the fetched engines are (default: the data folder)"
    )
    selfcheck.set_defaults(handler=_engines_selfcheck)
    sign_in = engines_actions.add_parser(
        "sign-in", help="sign an engine in with its own login, for one with no login command"
    )
    sign_in.add_argument("engine", help="the engine's name, such as antigravity")
    sign_in.add_argument("program", type=Path, help="the engine's program Nest installed")
    sign_in.set_defaults(handler=_engines_sign_in)
    engines_actions.add_parser(
        "registry",
        help="show where the ACP Registry lists newer versions of Nest's engines than it pins",
    ).set_defaults(handler=_engines_registry)
    return parser


def _move_folders(paths: AppPaths, rt: Runtime) -> list[str]:
    """Move the folders from before the rename to Nest (B43) before anything opens them;
    what was done. Only on macOS, where harness ran."""
    if not rt.platform.moves_legacy_folders:
        return []
    notes = [
        note for move in legacy_moves(rt.env, rt.home, rt.platform) if (note := move_folder(move))
    ]
    if adopt_legacy_database(paths.data_dir):
        notes.append(f"Renamed {LEGACY_DB_NAME} to {paths.db_path.name} in {paths.data_dir}")
    return notes


def _serve(args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    configure_logging(rt.err)
    # Before the switch, which writes in the data folder: a new one would stop the move.
    for note in _move_folders(paths, rt):
        logger.info(note)
    # Before this process opens anything: it may be replaced here.
    watch = switch_environment(
        Boot(
            root=paths.environments_dir,
            prefix=rt.prefix,
            executable=rt.executable,
            env=rt.env,
            exec_program=rt.exec_program,
        ),
        ["serve", *([] if args.port is None else ["--port", str(args.port)])],
    )
    os.environ.pop(SWITCHED_ENV, None)
    if is_packaged():
        note_start(paths.daemon_dir, __version__)
    # Engine processes inherit the daemon's environment (B98).
    drop_leaked_env(os.environ)
    # The server reads its token at startup; a missing or locked secret store stops here
    # with what to do, not with a traceback from inside the server.
    _read_token(rt)
    asyncio.run(_run_server(paths, rt, args.port, watch))
    return 0


def _read_token(rt: Runtime, sleep: Callable[[float], None] = time.sleep) -> None:
    """The local device token. At login the service can start a moment before the keyring
    is unlocked, which failed that start once on Ubuntu (B136): a locked store is asked
    again for a while, a missing one is not.
    """
    for _ in range(KEYRING_TRIES - 1):
        try:
            rt.secrets.get(LOCAL_DEVICE_ACCOUNT)
        except SecretStoreUnavailableError as error:
            if not error.locked:
                raise
            sleep(KEYRING_WAIT_SECONDS)
        else:
            return
    rt.secrets.get(LOCAL_DEVICE_ACCOUNT)


async def _run_server(
    paths: AppPaths, rt: Runtime, port: int | None, watch: TrialWatch | None
) -> None:
    ctx = await AppContext.build(paths, rt.secrets, rt.clock, platform=rt.platform)
    ctx.port_flag = port
    ctx.updates.watch = watch
    try:
        app = create_app(ctx, restart=partial(_restart, paths, rt.restart))
        await rt.serve(app, ctx.serving_port())
    finally:
        await ctx.close()


def _restart(paths: AppPaths, end: Restarter) -> None:
    """Every restart Nest asks for itself (Restart, Relaunch, Undo) is marked a clean stop
    first, so the update watcher does not count the start after it as a crash. Only here:
    uvicorn re-raises SIGTERM, so nothing after the server runs (B159 recheck 2 D).
    """
    if is_packaged():
        note_stop(paths.daemon_dir, __version__)
    end()


def _service(paths: AppPaths, rt: Runtime) -> ServiceManager:
    return service_manager(
        rt.platform,
        paths,
        rt.home,
        rt.env,
        rt.uid,
        rt.run_command,
        [rt.executable, "-m", "nestd", "serve"],
    )


def _service_install(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    service = _service(paths, rt)
    # The old daemon stops before its folders move, and they move before the service
    # file's log folder is made.
    if service.remove_legacy():
        print(f"Removed the service from before the rename ({LEGACY_LABEL})", file=rt.out)
    for note in _move_folders(paths, rt):
        print(note, file=rt.out)
    service.install()
    print(f"Installed and started {service.unit_path.stem} ({service.unit_path})", file=rt.out)
    print(f"Logs: {paths.logs_dir / 'daemon.log'}", file=rt.out)
    return 0


def _service_uninstall(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    service = _service(paths, rt)
    service.uninstall()
    print(f"Stopped and removed {service.unit_path.stem}", file=rt.out)
    return 0


def _service_status(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    status = _service(paths, rt).status()
    print(f"installed: {'yes' if status.installed else 'no'}", file=rt.out)
    print(f"loaded: {'yes' if status.loaded else 'no'}", file=rt.out)
    print(status.detail.rstrip(), file=rt.out)
    return 0 if status.loaded else 1


def _service_check_secrets(_args: argparse.Namespace, _paths: AppPaths, rt: Runtime) -> int:
    """For the install script: `nestd serve` stops at start without the store, and the
    guide is served by the daemon, so a missing one is reported before the service starts."""
    rt.secrets.get(LOCAL_DEVICE_ACCOUNT)
    return 0


def _service_wait(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    port = load_settings(paths).server.port
    if asyncio.run(_answers_within(port, SERVICE_WAIT_SECONDS)):
        return 0
    print(f"nestd: no answer on port {port} after {SERVICE_WAIT_SECONDS} seconds", file=rt.err)
    return 1


async def _answers_within(port: int, seconds: int) -> bool:
    for _ in range(seconds):
        if await answers_health(port):
            return True
        await asyncio.sleep(1)
    return False


def _pair(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    for note in _move_folders(paths, rt):
        print(note, file=rt.out)
    code = asyncio.run(_create_pairing_code(paths, rt))
    print(f"Pairing code: {code.code}", file=rt.out)
    print(f"Expires at {code.expires_at.astimezone():%H:%M:%S} (local time)", file=rt.out)
    return 0


async def _create_pairing_code(paths: AppPaths, rt: Runtime) -> PairingCode:
    ctx = await AppContext.build(paths, rt.secrets, rt.clock, platform=rt.platform)
    try:
        return await ctx.devices.create_pairing_code()
    finally:
        await ctx.close()


def _design_root(args: argparse.Namespace) -> Path:
    root: Path | None = args.root
    return root if root is not None else find_root(Path.cwd())


def _design_generate(args: argparse.Namespace, _paths: AppPaths, rt: Runtime) -> int:
    for path in generate(_design_root(args)):
        print(f"Wrote {path}", file=rt.out)
    return 0


def _design_icon(args: argparse.Namespace, _paths: AppPaths, rt: Runtime) -> int:
    try:
        written = generate_icons(_design_root(args))
    except ValueError as error:
        raise DesignError(str(error)) from error
    for path in written:
        print(f"Wrote {path}", file=rt.out)
    return 0


def _design_check(args: argparse.Namespace, _paths: AppPaths, rt: Runtime) -> int:
    problems = stale_outputs(_design_root(args))
    if not problems:
        print("Design tokens are up to date", file=rt.out)
        return 0
    for problem in problems:
        print(f"nestd: {problem}", file=rt.err)
    print("nestd: run `nestd design generate` to update them", file=rt.err)
    return 1


def _engines_selfcheck(args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    report = run_selfcheck_here(args.engines_dir or paths.engines_dir, rt.platform)
    print(report.model_dump_json(), file=rt.out)
    return 0 if report.ok else 1


def _engines_sign_in(args: argparse.Namespace, _paths: AppPaths, rt: Runtime) -> int:
    """The sign-in Settings shows for an engine Nest signs in itself (B153), run in a
    throwaway folder.
    """
    engine = next((found for found in ACP_ENGINES if found.id == args.engine), None)
    if engine is None or engine.login_method is None:
        print(f"nestd: {args.engine} signs in with its own command", file=rt.err)
        return 2
    launch = AcpLaunch((str(args.program), *engine.args), {**rt.env, **engine.env})
    print(f"Finish signing in to {engine.name} in your browser.", file=rt.out)
    try:
        with tempfile.TemporaryDirectory(prefix="nest-sign-in-") as folder:
            asyncio.run(sign_in(launch, Path(folder), engine.login_method))
    except TimeoutError:
        print("nestd: the sign-in was not finished in time", file=rt.err)
        return 1
    except (AcpRpcError, OSError) as error:
        print(f"nestd: {engine.name} could not sign in ({type(error).__name__})", file=rt.err)
        return 1
    print(f"Signed in to {engine.name}.", file=rt.out)
    return 0


def _engines_registry(_args: argparse.Namespace, _paths: AppPaths, rt: Runtime) -> int:
    """Where the pins in `acp_engines` lag the registry they come from (B153)."""
    try:
        entries = asyncio.run(_read_registry())
    except acp_registry.RegistryError as error:
        print(f"nestd: {error}", file=rt.err)
        return 1
    found = acp_registry.drift(ACP_ENGINES, entries, acp_registry.platform_name())
    if not found:
        print("Every engine matches the ACP Registry.", file=rt.out)
    for item in found:
        print(
            f"{item.engine}: pinned {item.pinned}, listed {item.listed}: {item.note}", file=rt.out
        )
    return 0


async def _read_registry() -> dict[str, acp_registry.Entry]:
    async with httpx.AsyncClient(timeout=acp_registry.REGISTRY_TIME_LIMIT) as client:
        return await acp_registry.fetch(client)


def _engines_install(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    """Each bundled engine's pinned version (B107); quick when they are all there."""
    return asyncio.run(_install_engines(paths, rt))


async def _install_engines(paths: AppPaths, rt: Runtime) -> int:
    shell = LoginShellEnv(login_shell(rt.env, rt.uid))

    async def env() -> dict[str, str]:
        return {**rt.env, **await shell.get()}

    failed = False
    for engine in ACP_ENGINES:
        if engine.delivery != "bundled":
            continue
        state = await EngineInstall(
            engine, paths.engines_dir, run_npm, env, rt.home, environments=paths.environments_dir
        ).install()
        if state.state == "ready":
            print(f"{engine.name} {state.version} is installed", file=rt.out)
        else:
            failed = True
            print(f"nestd: could not install {engine.name}: {state.detail}", file=rt.err)
    return 1 if failed else 0


# How many changed paths to name per part before summarising the rest.
_NAMED_PATHS = 3


def _gates_changed(args: argparse.Namespace, _paths: AppPaths, rt: Runtime) -> int:
    root: Path = args.root if args.root is not None else repository_root(Path.cwd())
    since = merge_base(root, args.base)
    selection = select(changed_paths(root, since))
    if selection.choices:
        count = len(selection.choices)
        print(
            f"{count} changed {'file' if count == 1 else 'files'} since {args.base} "
            f"(merge base {since[:7]})",
            file=rt.err,
        )
    else:
        print(f"no changes since {args.base} (merge base {since[:7]})", file=rt.err)
    for line in _explain(selection):
        print(line, file=rt.err)
    print(" ".join(selection.parts), file=rt.out)
    return 0


def _gates_record(args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    """`make check` times each part's stages (B115); Settings > Performance shows them."""
    try:
        parts = stage_times(args.stages)
    except ValueError as error:
        raise GatesError(str(error)) from error
    GateTimes.in_folder(paths.data_dir).record(
        GateRun(at=rt.clock.now(), parts=parts, total_ms=args.total)
    )
    return 0


def _explain(selection: Selection) -> list[str]:
    lines = [f"{c.path}: {c.reason}, no gate" for c in selection.choices if not c.parts]
    for part in ALL_PARTS:
        choices = selection.because(part)
        if not choices:
            lines.append(f"{part}: skipped (no changes)")
            continue
        named = [c.path if c.reason == part else f"{c.path} [{c.reason}]" for c in choices]
        shown = ", ".join(named[:_NAMED_PATHS])
        rest = len(named) - _NAMED_PATHS
        lines.append(f"{part}: runs ({shown}{f' and {rest} more' if rest > 0 else ''})")
    return lines
