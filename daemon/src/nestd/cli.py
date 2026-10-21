"""Command line entry point.

`nestd serve | service install|uninstall|status | pair | design generate|check|icon |
gates changed`.
"""

import argparse
import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from nestd.api.app import create_app
from nestd.auth.models import PairingCode
from nestd.config.errors import ConfigError
from nestd.context import AppContext
from nestd.design.errors import DesignError
from nestd.design.icon import generate_icons
from nestd.design.loader import find_root
from nestd.design.outputs import generate, stale_outputs
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
from nestd.paths import AppPaths
from nestd.runtime import Runtime, default_runtime
from nestd.service.launchd import LEGACY_LABEL, LaunchdService, ServiceError, build_path_env
from nestd.storage.errors import DatabaseError

type Handler = Callable[[argparse.Namespace, AppPaths, Runtime], int]

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None, runtime: Runtime | None = None) -> int:
    rt = runtime or default_runtime()
    args = _parser().parse_args(argv)
    handler: Handler = args.handler
    try:
        return handler(args, AppPaths.from_env(rt.env, rt.home), rt)
    except (
        ConfigError,
        DatabaseError,
        DesignError,
        FolderMoveError,
        GatesError,
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

    service = commands.add_parser("service", help="manage the launchd service")
    actions = service.add_subparsers(required=True, metavar="action")
    for name, handler, help_text in (
        ("install", _service_install, "install and start the service"),
        ("uninstall", _service_uninstall, "stop and remove the service"),
        ("status", _service_status, "show whether the service is installed and loaded"),
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
    return parser


def _move_folders(paths: AppPaths, rt: Runtime) -> list[str]:
    """Move the folders from before the rename to Nest (B43) before anything opens them;
    what was done."""
    notes = [note for move in legacy_moves(rt.env, rt.home) if (note := move_folder(move))]
    if adopt_legacy_database(paths.data_dir):
        notes.append(f"Renamed {LEGACY_DB_NAME} to {paths.db_path.name} in {paths.data_dir}")
    return notes


def _serve(args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    configure_logging(rt.err)
    for note in _move_folders(paths, rt):
        logger.info(note)
    asyncio.run(_run_server(paths, rt, args.port))
    return 0


async def _run_server(paths: AppPaths, rt: Runtime, port: int | None) -> None:
    ctx = await AppContext.build(paths, rt.secrets, rt.clock)
    try:
        app = create_app(ctx, restart=rt.restart)
        await rt.serve(app, port if port is not None else ctx.settings.server.port)
    finally:
        await ctx.close()


def _launchd(paths: AppPaths, rt: Runtime) -> LaunchdService:
    return LaunchdService(
        paths=paths,
        launch_agents_dir=rt.home / "Library" / "LaunchAgents",
        uid=rt.uid,
        runner=rt.run_command,
        program_args=[rt.executable, "-m", "nestd", "serve"],
        path_env=build_path_env(rt.home),
    )


def _service_install(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    service = _launchd(paths, rt)
    # The old daemon stops before its folders move, and they move before the plist's
    # log folder is made.
    if service.remove_legacy():
        print(f"Removed the service from before the rename ({LEGACY_LABEL})", file=rt.out)
    for note in _move_folders(paths, rt):
        print(note, file=rt.out)
    service.install()
    print(f"Installed and started {service.plist_path.stem} ({service.plist_path})", file=rt.out)
    print(f"Logs: {paths.logs_dir / 'daemon.log'}", file=rt.out)
    return 0


def _service_uninstall(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    service = _launchd(paths, rt)
    service.uninstall()
    print(f"Stopped and removed {service.plist_path.stem}", file=rt.out)
    return 0


def _service_status(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    status = _launchd(paths, rt).status()
    print(f"installed: {'yes' if status.installed else 'no'}", file=rt.out)
    print(f"loaded: {'yes' if status.loaded else 'no'}", file=rt.out)
    print(status.detail.rstrip(), file=rt.out)
    return 0 if status.loaded else 1


def _pair(_args: argparse.Namespace, paths: AppPaths, rt: Runtime) -> int:
    for note in _move_folders(paths, rt):
        print(note, file=rt.out)
    code = asyncio.run(_create_pairing_code(paths, rt))
    print(f"Pairing code: {code.code}", file=rt.out)
    print(f"Expires at {code.expires_at.astimezone():%H:%M:%S} (local time)", file=rt.out)
    return 0


async def _create_pairing_code(paths: AppPaths, rt: Runtime) -> PairingCode:
    ctx = await AppContext.build(paths, rt.secrets, rt.clock)
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
